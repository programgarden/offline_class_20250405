"""선물 매매 엔진: 돈치안 채널 돌파 매수 + 트레일링 스탑 매도 (계약 단위)"""
import logging
import math
from datetime import datetime, timedelta

import config
from analyzer.trend_analyzer import calc_donchian, calc_atr
from database import repository as repo
from trader.futures_client import FuturesClient, get_front_month_symbol

log = logging.getLogger(__name__)


class FuturesEngine:
    def __init__(self, client: FuturesClient, notify_fn=None, on_buy_fn=None):
        self.client = client
        self.notify = notify_fn or (lambda msg: None)
        self.on_buy = on_buy_fn  # 매수 후 콜백 (실시간 구독용)

    async def _is_paused(self) -> bool:
        paused = await repo.get_setting("futures_trading_paused")
        risk = await repo.get_setting("futures_risk_stopped")
        return paused == "1" or risk == "1"

    # ── 종목 심볼 및 스펙 준비 ───────────────────────────

    async def prepare_symbols(self) -> list[dict]:
        """마스터 데이터에서 거래 대상 근월물 심볼 + 스펙 생성"""
        symbols = []
        for item in config.FUTURES_SYMBOLS:
            # 마스터 데이터에서 근월물 조회 (폴백: 계산 기반)
            symbol = await self.client.get_front_symbol(item["base"])
            if not symbol:
                symbol = get_front_month_symbol(
                    item["base"], quarterly=item.get("quarterly", True))
                log.warning("[선물] 마스터에서 %s 미발견, 폴백 심볼: %s",
                            item["base"], symbol)

            # DB에서 스펙 캐시 확인
            spec = await repo.get_futures_spec(item["base"])
            if not spec:
                # API에서 현재가 조회로 스펙 가져오기
                price_data = await self.client.get_price(symbol)
                if price_data:
                    await repo.upsert_futures_spec(
                        base_symbol=item["base"],
                        name=item["name"],
                        exchange=item["exchange"],
                        tick_size=price_data["tick_size"],
                        tick_value=price_data["tick_value"],
                        margin_required=price_data["opening_margin"],
                    )
                    spec = await repo.get_futures_spec(item["base"])

            if spec:
                symbols.append({
                    "symbol": symbol,
                    "base": item["base"],
                    "name": item["name"],
                    "exchange": item["exchange"],
                    "tick_size": spec["tick_size"],
                    "tick_value": spec["tick_value"],
                    "margin_required": spec.get("margin_required", 0),
                })
        return symbols

    # ── 매수 로직 ────────────────────────────────────────

    async def check_and_buy(self, target_symbols: list[dict]):
        """돈치안 채널 돌파 종목 매수 (계약 단위)"""
        if await self._is_paused():
            log.info("[선물] 매매 중단 상태 - 매수 건너뜀")
            return

        settings = await repo.get_all_settings()
        donchian_period = int(settings.get("futures_donchian_period",
                                           config.FUTURES_DONCHIAN_PERIOD))
        atr_mult = float(settings.get("futures_atr_multiplier",
                                       config.FUTURES_ATR_MULTIPLIER))
        max_contracts = int(settings.get("futures_max_contracts",
                                          config.FUTURES_MAX_CONTRACTS))
        risk_per_trade = float(settings.get("futures_risk_per_trade",
                                             config.FUTURES_RISK_PER_TRADE))

        # 예수금 확인
        balance = await self.client.get_balance()
        if not balance:
            log.error("[선물] 예수금 조회 실패")
            return

        equity = balance.get("eval_asset", 0) or balance.get("deposit", 0)
        orderable = balance.get("orderable", 0)

        # 증거금 사용률 체크
        margin_used = balance.get("margin_used", 0)
        if equity > 0:
            margin_rate = (margin_used / equity) * 100
            if margin_rate >= config.FUTURES_MARGIN_LIMIT_PCT:
                log.info("[선물] 증거금 사용률 %.1f%% - 매수 건너뜀", margin_rate)
                return

        positions = await repo.get_futures_positions()
        current_count = len(positions)
        if current_count >= max_contracts:
            log.info("[선물] 최대 보유 종목 수(%d) 도달 - 매수 건너뜀", max_contracts)
            return

        held_symbols = {p["symbol"] for p in positions}
        held_bases = {p["base_symbol"] for p in positions}

        for item in target_symbols:
            symbol = item["symbol"]
            base = item["base"]
            tick_size = item["tick_size"]
            tick_value = item["tick_value"]

            if symbol in held_symbols or base in held_bases:
                continue

            # 차트 데이터 조회 (120일)
            end_date = datetime.utcnow().strftime("%Y%m%d")
            start_date = (datetime.utcnow() - timedelta(days=180)).strftime("%Y%m%d")
            candles = await self.client.get_daily_chart(symbol, start_date, end_date)
            if len(candles) < donchian_period + 1:
                continue

            # 돈치안 채널 + ATR 계산
            donchian = calc_donchian(candles, donchian_period)
            atr = calc_atr(candles, donchian_period)
            last_close = candles[-1]["close"]

            if last_close <= donchian["upper"]:
                continue  # 돌파 아님

            # 계약 수 계산: (예수금 × 리스크%) / (ATR × 틱밸류 / 틱사이즈)
            if tick_size <= 0 or tick_value <= 0 or atr <= 0:
                continue

            risk_amount = equity * (risk_per_trade / 100)
            one_contract_risk = atr * (tick_value / tick_size)
            quantity = math.floor(risk_amount / one_contract_risk)
            if quantity <= 0:
                quantity = 1  # 최소 1계약

            # 증거금 충분한지 확인
            margin_needed = item.get("margin_required", 0) * quantity
            if margin_needed > 0 and margin_needed > orderable:
                log.info("[선물] 증거금 부족 %s: 필요 $%.0f > 가능 $%.0f",
                         symbol, margin_needed, orderable)
                continue

            # 트레일링 스탑 가격 (LONG)
            stop_price = last_close - atr * atr_mult

            # 주문 실행
            result = await self.client.place_order(
                symbol, quantity, last_close,
                is_buy=True, market_order=False,
            )
            order_no = result.get("order_no", "")
            if not order_no:
                log.error("[선물] 매수 주문 실패: %s", symbol)
                continue

            # 포지션 & 거래 기록 저장
            await repo.upsert_futures_position(
                symbol=symbol,
                base_symbol=base,
                direction="LONG",
                quantity=quantity,
                avg_entry_price=last_close,
                highest_price=last_close,
                lowest_price=last_close,
                trailing_stop_price=stop_price,
                atr=atr,
                tick_size=tick_size,
                tick_value=tick_value,
                entry_date=datetime.utcnow().strftime("%Y-%m-%d"),
            )
            await repo.save_futures_trade(
                symbol=symbol,
                base_symbol=base,
                direction="LONG",
                order_type="ENTRY",
                order_no=order_no,
                quantity=quantity,
                price=last_close,
                pnl=None,
                reason="ENTRY",
            )

            pnl_per_tick = tick_value / tick_size if tick_size > 0 else 0
            msg = (
                f"[선물] 매수 {symbol} ({item['name']}) "
                f"{quantity}계약 @ {last_close}\n"
                f"스탑: {stop_price:.2f} (ATR {atr:.2f} x {atr_mult})\n"
                f"1계약 리스크: ${one_contract_risk:,.0f}"
            )
            log.info(msg)
            await self.notify(msg)

            if self.on_buy:
                try:
                    await self.on_buy(symbol)
                except Exception as e:
                    log.warning("[선물] 실시간 구독 추가 실패: %s - %s", symbol, e)

    # ── 매도 (트레일링 스탑) ─────────────────────────────

    async def check_trailing_stops(self):
        """보유 선물 포지션의 트레일링 스탑 체크"""
        settings = await repo.get_all_settings()
        atr_mult = float(settings.get("futures_atr_multiplier",
                                       config.FUTURES_ATR_MULTIPLIER))

        positions = await repo.get_futures_positions()
        if not positions:
            return

        for pos in positions:
            symbol = pos["symbol"]
            price_data = await self.client.get_price(symbol)
            if not price_data:
                continue

            current_price = price_data["price"]
            highest = pos["highest_price"]
            atr = pos["atr"]

            if pos["direction"] == "LONG":
                # 최고가 갱신
                if current_price > highest:
                    new_stop = current_price - atr * atr_mult
                    await repo.upsert_futures_position(
                        symbol=symbol,
                        base_symbol=pos["base_symbol"],
                        direction=pos["direction"],
                        quantity=pos["quantity"],
                        avg_entry_price=pos["avg_entry_price"],
                        highest_price=current_price,
                        lowest_price=pos["lowest_price"],
                        trailing_stop_price=new_stop,
                        atr=atr,
                        tick_size=pos["tick_size"],
                        tick_value=pos["tick_value"],
                        entry_date=pos["entry_date"],
                    )
                    continue

                # 트레일링 스탑 도달 → 매도
                if current_price <= pos["trailing_stop_price"]:
                    await self._close_position(pos, current_price, "TRAILING_STOP")

    async def _close_position(self, pos: dict, price: float, reason: str):
        """포지션 청산 (반대매매)"""
        symbol = pos["symbol"]
        quantity = pos["quantity"]
        is_buy = pos["direction"] == "SHORT"  # 반대매매

        result = await self.client.place_order(
            symbol, quantity, price,
            is_buy=is_buy, market_order=True,
        )
        order_no = result.get("order_no", "")
        if not order_no:
            log.error("[선물] 청산 주문 실패: %s", symbol)
            return

        # 손익 계산
        tick_size = pos["tick_size"]
        tick_value = pos["tick_value"]
        if pos["direction"] == "LONG":
            pnl = (price - pos["avg_entry_price"]) * (tick_value / tick_size) * quantity
        else:
            pnl = (pos["avg_entry_price"] - price) * (tick_value / tick_size) * quantity

        await repo.save_futures_trade(
            symbol=symbol,
            base_symbol=pos["base_symbol"],
            direction=pos["direction"],
            order_type="EXIT",
            order_no=order_no,
            quantity=quantity,
            price=price,
            pnl=pnl,
            reason=reason,
        )
        await repo.delete_futures_position(symbol)

        msg = (
            f"[선물] 청산 {symbol} {quantity}계약 @ {price} ({reason})\n"
            f"손익: ${pnl:+,.2f}"
        )
        log.info(msg)
        await self.notify(msg)

    # ── 리스크 청산용 일괄 매도 ──────────────────────────

    async def close_losing_positions(self):
        """마이너스 포지션만 청산 (3% 경고)"""
        positions = await repo.get_futures_positions()
        for pos in positions:
            price_data = await self.client.get_price(pos["symbol"])
            if not price_data:
                continue
            current = price_data["price"]
            if pos["direction"] == "LONG" and current < pos["avg_entry_price"]:
                await self._close_position(pos, current, "RISK_WARN")
            elif pos["direction"] == "SHORT" and current > pos["avg_entry_price"]:
                await self._close_position(pos, current, "RISK_WARN")

    async def close_all_positions(self):
        """전 포지션 청산 (5% 비상)"""
        positions = await repo.get_futures_positions()
        for pos in positions:
            price_data = await self.client.get_price(pos["symbol"])
            if not price_data:
                continue
            await self._close_position(pos, price_data["price"], "RISK_STOP")
