"""LS증권 API 클라이언트 (국내주식)"""
import asyncio
import logging
from programgarden_finance import LS
from programgarden_finance.ls.models import SetupOptions
from programgarden_finance.ls.korea_stock.accno.CSPAQ12300.blocks import CSPAQ12300InBlock1
from programgarden_finance.ls.korea_stock.accno.FOCCQ33600.blocks import FOCCQ33600InBlock1
from programgarden_finance.ls.korea_stock.chart.t8451.blocks import T8451InBlock
from programgarden_finance.ls.korea_stock.market.t1102.blocks import T1102InBlock
from programgarden_finance.ls.korea_stock.order.CSPAT00601.blocks import CSPAT00601InBlock1

import config

log = logging.getLogger(__name__)

_rate_opts = SetupOptions(
    rate_limit_count=config.KRX_RATE_LIMIT_COUNT,
    rate_limit_seconds=config.KRX_RATE_LIMIT_SECONDS,
    on_rate_limit="wait",
)


class KrxClient:
    """국내주식 (KRX) 전용 LS 클라이언트"""

    def __init__(self):
        self.ls = LS()
        self._stock = None

    async def login(self):
        max_retries = config.API_MAX_RETRIES
        base_delay = config.API_RETRY_BASE_DELAY
        for attempt in range(1, max_retries + 1):
            try:
                appkey = config.KRX_APPKEY or config.LS_APPKEY
                secret = config.KRX_APPSECRETKEY or config.LS_APPSECRETKEY
                if not appkey or not secret:
                    raise RuntimeError("국내주식 API 키 미설정")
                ok = await self.ls.async_login(appkey=appkey, appsecretkey=secret)
                if ok:
                    self._stock = self.ls.korea_stock()
                    log.info("LS증권 국내주식 로그인 성공")
                    return
                raise RuntimeError("LS증권 국내주식 로그인 응답 실패")
            except Exception as e:
                if attempt == max_retries:
                    log.error("LS증권 국내주식 로그인 최종 실패 (%d회 시도)", max_retries)
                    raise
                delay = base_delay ** attempt
                log.warning("[KRX] 로그인 재시도 %d/%d (%d초 후): %s",
                            attempt, max_retries, delay, e)
                await asyncio.sleep(delay)

    async def reconnect(self):
        log.info("[KRX] 세션 재연결 시도")
        self.ls = LS()
        self._stock = None
        await self.login()

    @property
    def stock(self):
        if self._stock is None:
            raise RuntimeError("로그인이 필요합니다")
        return self._stock

    # ── 계좌(잔고+보유종목 한번에) ─────────────────────────
    async def get_account(self) -> dict:
        """예수금 + 잔고요약 + 보유종목을 한 번에 반환"""
        resp = await self._retry_call(self._get_account_raw)
        return resp or {"balance": {}, "holdings": []}

    async def _get_account_raw(self) -> dict:
        accno = self.stock.accno()
        resp = await accno.cspaq12300(
            body=CSPAQ12300InBlock1(),
            options=_rate_opts,
        ).req_async()

        if resp.status_code >= 400:
            log.error("[KRX] 계좌 조회 실패: %s", resp.error_msg)
            return {"balance": {}, "holdings": []}

        balance = {}
        if resp.block2:
            b = resp.block2
            balance = {
                "orderable": float(b.MnyOrdAbleAmt or 0),     # 주문가능
                "eval_amount": float(b.BalEvalAmt or 0),       # 평가금액
                "purchase_amount": float(b.PchsAmt or 0),      # 매입금액
                "eval_pnl": float(b.EvalPnl or 0),             # 평가손익
                "pnl_rate": float(b.PnlRat or 0),              # 손익률
                "total_asset": float(b.DpsastTotamt or 0),     # 예탁자산총액 = 총자산
                "deposit": float(b.Dps or 0),                  # 예수금
                "d2_deposit": float(b.D2Dps or 0),             # D+2 예수금
            }

        holdings = []
        if resp.block3:
            for item in resp.block3:
                qty = int(item.BalQty or 0)
                if qty <= 0:
                    continue
                holdings.append({
                    "symbol": item.IsuNo,
                    "name": item.IsuNm,
                    "quantity": qty,
                    "sell_able_qty": int(item.SellAbleQty or 0),
                    "avg_price": float(item.AvrUprc or 0),
                    "current_price": float(item.NowPrc or 0),
                    "eval_amount": float(item.BalEvalAmt or 0),
                    "pnl_amount": float(item.EvalPnl or 0),
                    "pnl_rate": float(item.PnlRat or 0),
                })
        return {"balance": balance, "holdings": holdings}

    async def get_balance(self) -> dict:
        acc = await self.get_account()
        return acc.get("balance", {})

    async def get_holdings(self) -> list[dict]:
        acc = await self.get_account()
        return acc.get("holdings", [])

    # ── 현재가 조회 ──────────────────────────────────────
    async def get_price(self, symbol: str) -> dict:
        resp = await self._retry_call(self._get_price_raw, symbol)
        return resp or {}

    async def _get_price_raw(self, symbol: str) -> dict:
        market = self.stock.market()
        resp = await market.t1102(
            body=T1102InBlock(shcode=symbol),
            options=_rate_opts,
        ).req_async()
        if resp.status_code >= 400:
            log.error("[KRX] 현재가 조회 실패 %s: %s", symbol, resp.error_msg)
            return {}
        b = resp.block
        return {
            "symbol": symbol,
            "name": getattr(b, "hname", "") or "",
            "price": float(getattr(b, "price", 0) or 0),
            "open": float(getattr(b, "open", 0) or 0),
            "high": float(getattr(b, "high", 0) or 0),
            "low": float(getattr(b, "low", 0) or 0),
            "volume": int(getattr(b, "volume", 0) or 0),
            "rate": float(getattr(b, "change", 0) or 0),
        }

    # ── 일봉 차트 (t8451) ────────────────────────────────
    async def get_daily_chart(self, symbol: str, start_date: str = "",
                              end_date: str = "99999999",
                              count: int = 250) -> list[dict]:
        """일봉 차트. start_date/end_date: YYYYMMDD"""
        chart = self.stock.chart()
        resp = await chart.t8451(
            body=T8451InBlock(
                shcode=symbol,
                gubun="2",          # 일봉
                qrycnt=count,
                sdate=start_date,
                edate=end_date,
                cts_date="",
                comp_yn="N",
                sujung="Y",
                exchgubun="K",
            ),
            options=_rate_opts,
        ).req_async()
        if resp.status_code >= 400:
            log.error("[KRX] 차트 조회 실패 %s: %s", symbol, resp.error_msg)
            return []
        candles = []
        if resp.block1:
            for c in resp.block1:
                candles.append({
                    "date": str(c.date),
                    "open": float(c.open or 0),
                    "high": float(c.high or 0),
                    "low": float(c.low or 0),
                    "close": float(c.close or 0),
                    "volume": int(c.jdiff_vol or 0),
                })
        return candles

    # ── 주문 (매수/매도) ─────────────────────────────────
    async def place_order(self, symbol: str, quantity: int, price: float,
                          is_buy: bool, market_order: bool = False) -> dict:
        resp = await self._retry_call(
            self._place_order_raw, symbol, quantity, price, is_buy, market_order,
        )
        return resp or {}

    async def _place_order_raw(self, symbol: str, quantity: int, price: float,
                               is_buy: bool, market_order: bool = False) -> dict:
        order = self.stock.order()
        resp = await order.cspat00601(
            body=CSPAT00601InBlock1(
                IsuNo=symbol,
                OrdQty=quantity,
                OrdPrc=0 if market_order else price,
                BnsTpCode="2" if is_buy else "1",      # 2=매수, 1=매도
                OrdprcPtnCode="03" if market_order else "00",  # 00=지정가, 03=시장가
                MgntrnCode="000",
                LoanDt="",
                OrdCndiTpCode="0",
            ),
            options=_rate_opts,
        ).req_async()
        if resp.status_code >= 400:
            log.error("[KRX] 주문 실패 %s: %s", symbol, resp.error_msg)
            return {}
        b = resp.block2
        return {
            "order_no": str(getattr(b, "OrdNo", "")),
            "name": getattr(b, "IsuNm", ""),
        }

    # ── 기간 수익률 (FOCCQ33600) — 한 번 호출로 일별 시계열 ──
    async def get_performance(self, days: int = 30) -> list[dict]:
        """기간 누적 수익률 시계열. 보유종목 무관, 계좌 자체의 시계열."""
        resp = await self._retry_call(self._get_performance_raw, days)
        return resp or []

    async def _get_performance_raw(self, days: int) -> list[dict]:
        from datetime import datetime, timedelta
        end = datetime.now().date()
        start = end - timedelta(days=days + 7)   # 영업일 보정
        accno = self.stock.accno()
        resp = await accno.foccq33600(
            body=FOCCQ33600InBlock1(
                QrySrtDt=start.strftime("%Y%m%d"),
                QryEndDt=end.strftime("%Y%m%d"),
                TermTp="1",
            ),
            options=_rate_opts,
        ).req_async()
        if resp.status_code >= 400:
            log.error("[KRX] 기간 수익률 조회 실패: %s", resp.error_msg)
            return []
        rows = []
        if resp.block3:
            for c in resp.block3:
                rows.append({
                    "date": str(c.BaseDt),
                    "eval_amount": float(c.EotEvalAmt or 0),
                    "pnl": float(c.EvalPnlAmt or 0),
                    "term_ern_rat": float(c.TermErnrat or 0),
                    "idx": float(c.Idx or 0),
                })
        rows.sort(key=lambda r: r["date"])
        return rows

    # ── 재시도 헬퍼 ──────────────────────────────────────
    async def _retry_call(self, fn, *args, **kwargs):
        max_retries = config.API_MAX_RETRIES
        base_delay = config.API_RETRY_BASE_DELAY
        for attempt in range(1, max_retries + 1):
            try:
                return await fn(*args, **kwargs)
            except Exception as e:
                if attempt == max_retries:
                    log.error("[KRX] %s 최종 실패 (%d회 시도): %s",
                              fn.__name__, max_retries, e)
                    return None
                delay = base_delay ** attempt
                log.warning("[KRX] %s 재시도 %d/%d (%d초 후): %s",
                            fn.__name__, attempt, max_retries, delay, e)
                await asyncio.sleep(delay)
