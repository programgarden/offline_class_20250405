"""국내주식 터틀 매매 엔진"""
import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from database import repository as repo

log = logging.getLogger(__name__)
KST = ZoneInfo("Asia/Seoul")


def _atr(candles: list[dict], period: int) -> float:
    if len(candles) < period + 1:
        return 0.0
    trs = []
    prev_close = candles[-period - 1]["close"]
    for c in candles[-period:]:
        tr = max(c["high"] - c["low"],
                 abs(c["high"] - prev_close),
                 abs(c["low"] - prev_close))
        trs.append(tr)
        prev_close = c["close"]
    return sum(trs) / len(trs)


def _donchian_high(candles: list[dict], period: int) -> float:
    if len(candles) < period:
        return 0.0
    return max(c["high"] for c in candles[-period:])


class KrxEngine:
    """국내주식 터틀 진입/청산"""

    def __init__(self, client, notify_fn=None):
        self.client = client
        self.notify = notify_fn or (lambda m: None)

    async def check_and_buy(self, universe: list[dict]):
        settings = await repo.get_all_settings()
        if settings.get("krx_trading_paused") == "1":
            return
        if settings.get("krx_risk_stopped") == "1":
            return

        mode = settings.get("krx_mode", "dry")
        donchian = int(settings.get("krx_donchian_period", 20))
        atr_mult = float(settings.get("krx_atr_multiplier", 3.0))
        max_stocks = int(settings.get("krx_max_stocks", 5))
        capital_ratio = float(settings.get("krx_capital_ratio", 50)) / 100.0

        positions = await repo.get_krx_positions()
        if len(positions) >= max_stocks:
            return
        held = {p["symbol"] for p in positions}

        balance = await self.client.get_balance()
        orderable = balance.get("orderable", 0)
        if orderable < 100_000:    # 10만원 미만이면 스킵
            return

        slot_cash = (orderable * capital_ratio) / max(1, max_stocks - len(positions))

        today = datetime.now(KST).strftime("%Y%m%d")
        for s in universe:
            symbol = s["symbol"]
            if symbol in held:
                continue
            try:
                candles = await self.client.get_daily_chart(
                    symbol=symbol, end_date=today, count=donchian + 30,
                )
                if len(candles) < donchian + 1:
                    continue
                # 마지막 봉이 돈치안 상단 돌파
                last = candles[-1]
                prior = candles[:-1]
                breakout = _donchian_high(prior, donchian)
                if breakout <= 0 or last["close"] < breakout:
                    continue
                atr = _atr(candles, 20)
                if atr <= 0:
                    continue

                # 매수 수량 = slot_cash / 종가
                qty = int(slot_cash // last["close"])
                if qty <= 0:
                    continue
                price = last["close"]
                stop = round(price - atr * atr_mult, 0)

                if mode == "live":
                    r = await self.client.place_order(
                        symbol=symbol, quantity=qty, price=price,
                        is_buy=True, market_order=False,
                    )
                    order_no = r.get("order_no", "")
                    name = r.get("name", s.get("name", ""))
                else:
                    order_no = "DRY"
                    name = s.get("name", "")

                await repo.upsert_krx_position(
                    symbol=symbol, name=name, quantity=qty,
                    avg_buy_price=price, highest_price=price,
                    trailing_stop_price=stop, atr=atr,
                    entry_date=today,
                )
                await repo.save_krx_trade(
                    symbol=symbol, name=name, order_type="BUY",
                    order_no=order_no, quantity=qty, price=price,
                    reason=f"돈치안{donchian}돌파", is_dry_run=(mode != "live"),
                )
                await self.notify(
                    f"[국내] 매수 {name}({symbol}) {qty}주 @ {price:,.0f}원"
                    f"{' [DRY]' if mode != 'live' else ''}"
                )
            except Exception as e:
                log.exception("[KRX] 매수 체크 오류 %s: %s", symbol, e)

    async def check_trailing_stops(self):
        settings = await repo.get_all_settings()
        mode = settings.get("krx_mode", "dry")
        atr_mult = float(settings.get("krx_atr_multiplier", 3.0))

        positions = await repo.get_krx_positions()
        if not positions:
            return
        holdings = {h["symbol"]: h for h in await self.client.get_holdings()}

        for p in positions:
            try:
                cur = holdings.get(p["symbol"], {}).get("current_price")
                if not cur:
                    pr = await self.client.get_price(p["symbol"])
                    cur = pr.get("price", 0)
                if not cur:
                    continue

                if cur > p["highest_price"]:
                    new_stop = round(cur - p["atr"] * atr_mult, 0)
                    await repo.upsert_krx_position(
                        symbol=p["symbol"], name=p["name"], quantity=p["quantity"],
                        avg_buy_price=p["avg_buy_price"], highest_price=cur,
                        trailing_stop_price=new_stop, atr=p["atr"],
                        entry_date=p["entry_date"],
                    )
                elif cur <= p["trailing_stop_price"]:
                    await self._sell(p, cur, "TRAILING_STOP", mode)
            except Exception as e:
                log.exception("[KRX] 스탑 체크 오류 %s: %s", p["symbol"], e)

    async def _sell(self, pos: dict, price: float, reason: str, mode: str):
        try:
            if mode == "live":
                r = await self.client.place_order(
                    symbol=pos["symbol"], quantity=pos["quantity"], price=price,
                    is_buy=False, market_order=False,
                )
                order_no = r.get("order_no", "")
            else:
                order_no = "DRY"

            await repo.save_krx_trade(
                symbol=pos["symbol"], name=pos.get("name", ""),
                order_type="SELL", order_no=order_no,
                quantity=pos["quantity"], price=price, reason=reason,
                is_dry_run=(mode != "live"),
            )
            await repo.delete_krx_position(pos["symbol"])
            await self.notify(
                f"[국내] 매도 {pos.get('name', '')}({pos['symbol']}) {pos['quantity']}주 @ {price:,.0f}원 ({reason})"
                f"{' [DRY]' if mode != 'live' else ''}"
            )
        except Exception as e:
            log.exception("[KRX] 매도 오류 %s: %s", pos["symbol"], e)
