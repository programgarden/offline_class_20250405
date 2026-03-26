"""매매 엔진: 돈치안 채널 돌파 매수 + 트레일링 스탑 매도"""
import logging
import math
from datetime import datetime

import config
from database import repository as repo
from trader.ls_client import LSClient

log = logging.getLogger(__name__)


class TradingEngine:
    def __init__(self, client: LSClient, notify_fn=None, on_buy_fn=None):
        self.client = client
        self.notify = notify_fn or (lambda msg: None)
        self.on_buy = on_buy_fn  # 매수 후 콜백 (실시간 구독용)

    async def _is_paused(self) -> bool:
        paused = await repo.get_setting("trading_paused")
        risk = await repo.get_setting("risk_stopped")
        return paused == "1" or risk == "1"

    async def _get_mode(self) -> str:
        return await repo.get_setting("mode") or config.DEFAULT_MODE

    # ── 매수 로직 ────────────────────────────────────────

    async def check_and_buy(self, selected_stocks: list[dict]):
        """선정된 종목 중 돈치안 채널 돌파 종목 매수"""
        if await self._is_paused():
            log.info("매매 중단 상태 - 매수 건너뜀")
            return

        mode = await self._get_mode()
        settings = await repo.get_all_settings()
        capital_ratio = int(settings.get("capital_ratio", config.CAPITAL_RATIO))
        max_stocks = int(settings.get("max_stocks", config.MAX_STOCKS))

        # 예수금 확인
        balance = await self.client.get_balance()
        if not balance:
            log.error("예수금 조회 실패")
            return

        orderable = balance["orderable"] * (capital_ratio / 100)
        positions = await repo.get_positions()
        current_count = len(positions)

        if current_count >= max_stocks:
            log.info("최대 보유 종목 수(%d) 도달 - 매수 건너뜀", max_stocks)
            return

        slots = max_stocks - current_count
        per_stock = orderable / slots if slots > 0 else 0

        held_symbols = {p["symbol"] for p in positions}

        for stock in selected_stocks:
            if stock["symbol"] in held_symbols:
                continue
            if not stock.get("is_breakout"):
                continue
            if per_stock <= 0:
                break

            symbol = stock["symbol"]
            exchange_code = stock["exchange_code"]
            price = stock["last_close"]
            atr = stock.get("atr", 0)

            if price <= 0:
                continue

            quantity = math.floor(per_stock / price)
            if quantity <= 0:
                continue

            # 트레일링 스탑 가격
            atr_mult = float(settings.get("atr_multiplier", config.ATR_MULTIPLIER))
            stop_price = round(price - atr * atr_mult, 2)

            if mode == config.MODE_LIVE:
                result = await self.client.place_order(
                    symbol, exchange_code, quantity, price,
                    is_buy=True, market_order=False,
                )
                order_no = result.get("order_no", "")
                if not order_no:
                    log.error("매수 주문 실패: %s", symbol)
                    continue
            else:
                order_no = f"DRY-{datetime.utcnow().strftime('%H%M%S')}"

            # 포지션 & 거래 기록 저장
            await repo.upsert_position(
                symbol=symbol,
                exchange_code=exchange_code,
                quantity=quantity,
                avg_buy_price=price,
                highest_price=price,
                trailing_stop_price=stop_price,
                atr=atr,
                entry_date=datetime.utcnow().strftime("%Y-%m-%d"),
            )
            await repo.save_trade(
                symbol, exchange_code, "BUY", order_no,
                quantity, price, "ENTRY",
                is_dry_run=(mode != config.MODE_LIVE),
            )

            msg = (
                f"{'[DRY] ' if mode != config.MODE_LIVE else ''}"
                f"매수 {symbol} {quantity}주 @ ${price:.2f}\n"
                f"스탑: ${stop_price:.2f} (ATR {atr:.2f} x {atr_mult})"
            )
            log.info(msg)
            await self.notify(msg)
            per_stock -= quantity * price

            # 실시간 구독 추가 (WebSocket)
            if self.on_buy:
                try:
                    await self.on_buy(symbol, exchange_code)
                except Exception as e:
                    log.warning("실시간 구독 추가 실패: %s - %s", symbol, e)

    # ── 매도 (트레일링 스탑) ─────────────────────────────

    async def check_trailing_stops(self):
        """보유 종목의 트레일링 스탑 체크 및 매도 실행"""
        mode = await self._get_mode()
        settings = await repo.get_all_settings()
        atr_mult = float(settings.get("atr_multiplier", config.ATR_MULTIPLIER))

        positions = await repo.get_positions()
        if not positions:
            return

        for pos in positions:
            symbol = pos["symbol"]
            exchange_code = pos["exchange_code"]

            price_data = await self.client.get_price(symbol, exchange_code)
            if not price_data:
                continue

            current_price = price_data["price"]
            highest = pos["highest_price"]
            atr = pos["atr"]

            # 최고가 갱신
            if current_price > highest:
                new_stop = round(current_price - atr * atr_mult, 2)
                await repo.upsert_position(
                    symbol=symbol,
                    exchange_code=exchange_code,
                    quantity=pos["quantity"],
                    avg_buy_price=pos["avg_buy_price"],
                    highest_price=current_price,
                    trailing_stop_price=new_stop,
                    atr=atr,
                    entry_date=pos["entry_date"],
                )
                continue

            # 트레일링 스탑 도달 → 매도
            if current_price <= pos["trailing_stop_price"]:
                await self._sell_position(pos, current_price, "TRAILING_STOP", mode)

    async def _sell_position(self, pos: dict, price: float, reason: str, mode: str):
        """포지션 매도 실행"""
        symbol = pos["symbol"]
        exchange_code = pos["exchange_code"]
        quantity = pos["quantity"]

        if mode == config.MODE_LIVE:
            result = await self.client.place_order(
                symbol, exchange_code, quantity, price,
                is_buy=False, market_order=True,
            )
            order_no = result.get("order_no", "")
            if not order_no:
                log.error("매도 주문 실패: %s", symbol)
                return
        else:
            order_no = f"DRY-{datetime.utcnow().strftime('%H%M%S')}"

        pnl = (price - pos["avg_buy_price"]) * quantity
        pnl_pct = ((price - pos["avg_buy_price"]) / pos["avg_buy_price"]) * 100

        await repo.save_trade(
            symbol, exchange_code, "SELL", order_no,
            quantity, price, reason,
            is_dry_run=(mode != config.MODE_LIVE),
        )
        await repo.delete_position(symbol)

        msg = (
            f"{'[DRY] ' if mode != config.MODE_LIVE else ''}"
            f"매도 {symbol} {quantity}주 @ ${price:.2f} ({reason})\n"
            f"손익: ${pnl:+.2f} ({pnl_pct:+.1f}%)"
        )
        log.info(msg)
        await self.notify(msg)

    # ── 리스크 청산용 일괄 매도 ──────────────────────────

    async def sell_losing_positions(self):
        """마이너스 종목만 청산 (4% 경고)"""
        mode = await self._get_mode()
        positions = await repo.get_positions()
        for pos in positions:
            price_data = await self.client.get_price(pos["symbol"], pos["exchange_code"])
            if not price_data:
                continue
            if price_data["price"] < pos["avg_buy_price"]:
                await self._sell_position(pos, price_data["price"], "RISK_WARN", mode)

    async def sell_all_positions(self):
        """전종목 청산 (5% 비상)"""
        mode = await self._get_mode()
        positions = await repo.get_positions()
        for pos in positions:
            price_data = await self.client.get_price(pos["symbol"], pos["exchange_code"])
            if not price_data:
                continue
            await self._sell_position(pos, price_data["price"], "RISK_STOP", mode)
