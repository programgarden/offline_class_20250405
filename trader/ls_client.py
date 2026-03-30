"""LS증권 API 클라이언트 래퍼"""
import asyncio
import logging
from programgarden_finance import LS
from programgarden_finance.ls.models import SetupOptions
from programgarden_finance.ls.overseas_stock.market.g3101.blocks import G3101InBlock
from programgarden_finance.ls.overseas_stock.market.g3190.blocks import G3190InBlock
from programgarden_finance.ls.overseas_stock.chart.g3204.blocks import G3204InBlock
from programgarden_finance.ls.overseas_stock.accno.COSOQ02701.blocks import COSOQ02701InBlock1
from programgarden_finance.ls.overseas_stock.accno.COSOQ00201.blocks import COSOQ00201InBlock1
from programgarden_finance.ls.overseas_stock.order.COSAT00301.blocks import COSAT00301InBlock1
import config

log = logging.getLogger(__name__)

_rate_opts = SetupOptions(
    rate_limit_count=config.RATE_LIMIT_COUNT,
    rate_limit_seconds=config.RATE_LIMIT_SECONDS,
    on_rate_limit="wait",
)


class LSClient:
    def __init__(self):
        self.ls = LS()
        self._stock = None

    async def login(self):
        """로그인 (지수 백오프 재시도)"""
        max_retries = config.API_MAX_RETRIES
        base_delay = config.API_RETRY_BASE_DELAY

        for attempt in range(1, max_retries + 1):
            try:
                ok = await self.ls.async_login(
                    appkey=config.LS_APPKEY,
                    appsecretkey=config.LS_APPSECRETKEY,
                )
                if ok:
                    self._stock = self.ls.overseas_stock()
                    log.info("LS증권 실전 로그인 성공")
                    return
                raise RuntimeError("LS증권 로그인 응답 실패")
            except Exception as e:
                if attempt == max_retries:
                    log.error("LS증권 로그인 최종 실패 (%d회 시도)", max_retries)
                    raise
                delay = base_delay ** attempt
                log.warning("로그인 재시도 %d/%d (%d초 후): %s", attempt, max_retries, delay, e)
                await asyncio.sleep(delay)

    async def reconnect(self):
        """세션 재연결 (기존 객체 초기화 후 재로그인)"""
        log.info("LS증권 세션 재연결 시도")
        self.ls = LS()
        self._stock = None
        await self.login()

    @property
    def stock(self):
        if self._stock is None:
            raise RuntimeError("로그인이 필요합니다")
        return self._stock

    # ── 예수금 조회 ──────────────────────────────────────

    async def get_balance(self) -> dict:
        """USD 예수금 및 주문가능금액 조회 (네트워크 오류 시 재시도)"""
        resp = await self._retry_call(self._get_balance_raw)
        if resp is None:
            return {}
        return resp

    async def _get_balance_raw(self) -> dict:
        accno = self.stock.accno()
        resp = await accno.cosoq02701(
            body=COSOQ02701InBlock1(RecCnt=1, CrcyCode="USD"),
            options=_rate_opts,
        ).req_async()

        if resp.status_code >= 400:
            log.error("예수금 조회 실패: %s", resp.error_msg)
            return {}

        result = {}
        if resp.block3:
            for item in resp.block3:
                if item.CrcyCode == "USD":
                    fcurr_ord = float(item.FcurrOrdAbleAmt)
                    prexch_ord = float(item.PrexchOrdAbleAmt)
                    result = {
                        "deposit": float(item.FcurrDps),
                        "orderable": fcurr_ord + prexch_ord,  # 외화+사전환전 합산
                        "orderable_fcurr": fcurr_ord,
                        "orderable_prexch": prexch_ord,
                        "exchange_rate": float(item.BaseXchrat),
                    }
                    break
        # 원화 잔고
        if resp.block4:
            result["won_balance"] = float(resp.block4.WonDpsBalAmt)
        return result

    # ── 보유종목 조회 ────────────────────────────────────

    async def get_holdings(self) -> list[dict]:
        """보유종목 목록 조회 (네트워크 오류 시 재시도)"""
        resp = await self._retry_call(self._get_holdings_raw)
        if resp is None:
            return []
        return resp

    async def _get_holdings_raw(self) -> list[dict]:
        accno = self.stock.accno()
        resp = await accno.cosoq00201(
            body=COSOQ00201InBlock1(RecCnt=1, BaseDt="", CrcyCode="ALL", AstkBalTpCode="00"),
            options=_rate_opts,
        ).req_async()

        if resp.status_code >= 400:
            log.error("보유종목 조회 실패: %s", resp.error_msg)
            return []

        holdings = []
        if resp.block4:
            for item in resp.block4:
                if int(item.AstkBalQty) <= 0:
                    continue
                holdings.append({
                    "symbol": item.ShtnIsuNo,
                    "name": item.JpnMktHanglIsuNm,
                    "quantity": int(item.AstkBalQty),
                    "sell_able_qty": int(item.AstkSellAbleQty),
                    "avg_price": float(item.FcstckUprc),
                    "current_price": float(item.OvrsScrtsCurpri),
                    "eval_amount": float(item.FcurrEvalAmt),
                    "pnl_amount": float(item.FcurrEvalPnlAmt),
                    "pnl_rate": float(item.PnlRat),
                    "market_code": item.FcurrMktCode,
                })
        return holdings

    # ── 현재가 조회 ──────────────────────────────────────

    async def get_price(self, symbol: str, exchange_code: str) -> dict:
        """종목 현재가 조회 (네트워크 오류 시 재시도)"""
        resp = await self._retry_call(self._get_price_raw, symbol, exchange_code)
        if resp is None:
            return {}
        return resp

    async def _get_price_raw(self, symbol: str, exchange_code: str) -> dict:
        market = self.stock.market()
        keysymbol = f"{exchange_code}{symbol}"
        resp = await market.g3101(
            body=G3101InBlock(
                delaygb="R",
                keysymbol=keysymbol,
                exchcd=exchange_code,
                symbol=symbol,
            ),
            options=_rate_opts,
        ).req_async()

        if resp.status_code >= 400:
            log.error("현재가 조회 실패 %s: %s", symbol, resp.error_msg)
            return {}

        b = resp.block
        return {
            "symbol": symbol,
            "name": b.korname,
            "price": float(b.price),
            "open": float(b.open),
            "high": float(b.high),
            "low": float(b.low),
            "volume": int(b.volume),
            "rate": float(b.rate),
        }

    # ── 일봉 차트 조회 ──────────────────────────────────

    async def get_daily_chart(self, symbol: str, exchange_code: str,
                              start_date: str, end_date: str,
                              count: int = 100) -> list[dict]:
        """일봉 데이터 조회. start_date/end_date: YYYYMMDD"""
        chart = self.stock.chart()
        keysymbol = f"{exchange_code}{symbol}"
        resp = await chart.g3204(
            body=G3204InBlock(
                sujung="Y",
                delaygb="R",
                comp_yn="N",
                keysymbol=keysymbol,
                exchcd=exchange_code,
                symbol=symbol,
                gubun="2",  # 일봉
                qrycnt=count,
                sdate=start_date,
                edate=end_date,
                cts_date="",
                cts_info="",
            ),
            options=_rate_opts,
        ).req_async()

        if resp.status_code >= 400:
            log.error("차트 조회 실패 %s: %s", symbol, resp.error_msg)
            return []

        candles = []
        if resp.block1:
            for c in resp.block1:
                candles.append({
                    "date": c.date,
                    "open": float(c.open),
                    "high": float(c.high),
                    "low": float(c.low),
                    "close": float(c.close),
                    "volume": int(c.volume),
                })
        return candles

    # ── 종목 리스트 조회 ─────────────────────────────────

    async def get_stock_list(self, exchange_code: str) -> list[dict]:
        """거래소별 상장 종목 리스트 조회 (페이징 자동 처리)"""
        market = self.stock.market()
        all_stocks = []

        async def _callback(resp, status):
            if resp and resp.block1:
                for item in resp.block1:
                    all_stocks.append({
                        "keysymbol": item.keysymbol,
                        "symbol": item.symbol,
                        "name_kr": item.korname,
                        "name_en": item.engname,
                        "exchange_code": item.exchcd,
                        "market_cap": int(item.marketcap) if item.marketcap else 0,
                        "shares": int(item.share) if item.share else 0,
                        "last_close": float(item.clos) if item.clos else 0,
                        "listed_date": item.listed_date,
                        "suspended": item.suspend == "Y",
                    })

        await market.g3190(
            body=G3190InBlock(
                delaygb="R",
                natcode="840",
                exgubun=exchange_code,
                readcnt=500,
                cts_value="",
            ),
            options=_rate_opts,
        ).occurs_req_async(callback=_callback)

        return all_stocks

    # ── 주문 (매수/매도) ─────────────────────────────────

    async def place_order(self, symbol: str, exchange_code: str,
                          quantity: int, price: float,
                          is_buy: bool, market_order: bool = False) -> dict:
        """주문 실행 (네트워크 오류 시 재시도). 성공 시 {order_no, name} 반환"""
        resp = await self._retry_call(
            self._place_order_raw, symbol, exchange_code,
            quantity, price, is_buy, market_order,
        )
        if resp is None:
            return {}
        return resp

    async def _place_order_raw(self, symbol: str, exchange_code: str,
                               quantity: int, price: float,
                               is_buy: bool, market_order: bool = False) -> dict:
        order = self.stock.order()
        resp = await order.cosat00301(
            body=COSAT00301InBlock1(
                RecCnt=1,
                OrdPtnCode="01" if is_buy else "02",
                OrdMktCode=exchange_code,
                IsuNo=symbol,
                OrdQty=quantity,
                OvrsOrdPrc=0 if market_order else price,
                OrdprcPtnCode="00" if market_order else "03",
                BrkTpCode="",
            ),
            options=_rate_opts,
        ).req_async()

        if resp.status_code >= 400:
            log.error("주문 실패 %s: %s", symbol, resp.error_msg)
            return {}

        return {
            "order_no": str(resp.block2.OrdNo),
            "name": resp.block2.IsuNm,
        }

    # ── 재시도 헬퍼 ──────────────────────────────────────

    async def _retry_call(self, fn, *args, **kwargs):
        """API 호출 재시도 래퍼 (네트워크/예외 발생 시 지수 백오프)"""
        max_retries = config.API_MAX_RETRIES
        base_delay = config.API_RETRY_BASE_DELAY

        for attempt in range(1, max_retries + 1):
            try:
                return await fn(*args, **kwargs)
            except Exception as e:
                if attempt == max_retries:
                    log.error("%s 최종 실패 (%d회 시도): %s", fn.__name__, max_retries, e)
                    return None
                delay = base_delay ** attempt
                log.warning("%s 재시도 %d/%d (%d초 후): %s",
                            fn.__name__, attempt, max_retries, delay, e)
                await asyncio.sleep(delay)
