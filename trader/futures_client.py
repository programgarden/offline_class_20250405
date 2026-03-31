"""해외선물 API 클라이언트 래퍼 (모의투자)"""
import asyncio
import logging
from datetime import datetime, date

from programgarden_finance import LS
from programgarden_finance.ls.models import SetupOptions
from programgarden_finance.ls.overseas_futureoption.market.o3101.blocks import O3101InBlock
from programgarden_finance.ls.overseas_futureoption.market.o3105.blocks import O3105InBlock
from programgarden_finance.ls.overseas_futureoption.chart.o3108.blocks import O3108InBlock
from programgarden_finance.ls.overseas_futureoption.accno.CIDBQ03000.blocks import CIDBQ03000InBlock1
from programgarden_finance.ls.overseas_futureoption.accno.CIDBQ01500.blocks import CIDBQ01500InBlock1
from programgarden_finance.ls.overseas_futureoption.order.CIDBT00100.blocks import CIDBT00100InBlock1
import config

log = logging.getLogger(__name__)

_rate_opts = SetupOptions(
    rate_limit_count=config.FUTURES_RATE_LIMIT_COUNT,
    rate_limit_seconds=config.FUTURES_RATE_LIMIT_SECONDS,
    on_rate_limit="wait",
)


def get_front_month_symbol(base: str, quarterly: bool = True,
                           ref_date: date | None = None) -> str:
    """기초상품 코드로 근월물 심볼 생성 (폴백용).
    실제 운영에서는 FuturesClient.get_front_symbol()을 사용하여
    마스터 데이터에서 정확한 근월물을 가져옵니다."""
    today = ref_date or date.today()
    month_codes = config.FUTURES_MONTH_CODES

    if quarterly:
        months = config.FUTURES_QUARTER_MONTHS
    else:
        months = list(range(1, 13))

    # 현재 월 다음달부터 찾기 (현재 월은 이미 만기 가능성)
    target_month = None
    target_year = today.year

    for m in months:
        if m > today.month:
            target_month = m
            break
    if target_month is None:
        target_month = months[0]
        target_year += 1

    code = month_codes[target_month]
    yr = str(target_year)[-2:]
    return f"{base}{code}{yr}"


class FuturesClient:
    def __init__(self):
        self.ls = LS()
        self._futures = None
        self._master_cache: list[dict] = []  # 마스터 데이터 캐시

    async def login(self):
        """모의투자 로그인 (지수 백오프 재시도)"""
        max_retries = config.API_MAX_RETRIES
        base_delay = config.API_RETRY_BASE_DELAY

        for attempt in range(1, max_retries + 1):
            try:
                ok = await self.ls.async_login(
                    appkey=config.FUTURES_LS_APPKEY,
                    appsecretkey=config.FUTURES_LS_APPSECRETKEY,
                    paper_trading=True,
                )
                if ok:
                    self._futures = self.ls.overseas_futureoption()
                    log.info("LS증권 해외선물 모의투자 로그인 성공")
                    return
                raise RuntimeError("해외선물 로그인 응답 실패")
            except Exception as e:
                if attempt == max_retries:
                    log.error("해외선물 로그인 최종 실패 (%d회 시도)", max_retries)
                    raise
                delay = base_delay ** attempt
                log.warning("선물 로그인 재시도 %d/%d (%d초 후): %s",
                            attempt, max_retries, delay, e)
                await asyncio.sleep(delay)

    async def reconnect(self):
        """세션 재연결"""
        log.info("해외선물 세션 재연결 시도")
        self.ls = LS()
        self._futures = None
        await self.login()

    @property
    def futures(self):
        if self._futures is None:
            raise RuntimeError("해외선물 로그인이 필요합니다")
        return self._futures

    # ── 마스터 조회 (종목 목록 + 틱정보) ─────────────────

    async def get_master_list(self) -> list[dict]:
        """해외선물 마스터(종목 목록 + 틱사이즈/밸류/증거금) 조회"""
        resp = await self._retry_call(self._get_master_raw)
        return resp if resp else []

    async def _get_master_raw(self) -> list[dict]:
        market = self.futures.market()
        resp = await market.o3101(
            body=O3101InBlock(gubun=""),
            options=_rate_opts,
        ).req_async()

        if resp.status_code >= 400:
            log.error("선물 마스터 조회 실패: %s", resp.error_msg)
            return []

        items = []
        if resp.block:
            for item in resp.block:
                items.append({
                    "symbol": item.Symbol,
                    "name": item.SymbolNm,
                    "base_code": item.BscGdsCd,
                    "base_name": item.BscGdsNm,
                    "exchange": item.ExchNm,
                    "exchange_code": item.ExchCd,
                    "tick_size": float(item.UntPrc) if item.UntPrc else 0,
                    "tick_value": float(item.MnChgAmt) if item.MnChgAmt else 0,
                    "opening_margin": float(item.OpngMgn) if item.OpngMgn else 0,
                    "maintenance_margin": float(item.MntncMgn) if item.MntncMgn else 0,
                    "tradable": item.DlPsblCd,
                })
        self._master_cache = items
        return items

    async def get_front_symbol(self, base: str) -> str | None:
        """마스터 데이터에서 기초상품의 근월물(가장 가까운 거래가능 심볼) 반환."""
        if not self._master_cache:
            await self.get_master_list()

        # 월코드 → 월 번호 역매핑
        code_to_month = {v: k for k, v in config.FUTURES_MONTH_CODES.items()}

        candidates = [
            m["symbol"] for m in self._master_cache
            if m["base_code"] == base and m["tradable"] == "1"
        ]
        if not candidates:
            return None

        def _sort_key(sym: str) -> tuple[int, int]:
            """심볼에서 (연도, 월) 추출하여 정렬 키 생성"""
            # 심볼 = base + month_code(1글자) + year(2자리)
            yr_str = sym[-2:]      # "26"
            mc = sym[-(2+1):-2]    # 월코드 1글자
            yr = 2000 + int(yr_str)
            month = code_to_month.get(mc, 0)
            return (yr, month)

        candidates.sort(key=_sort_key)
        return candidates[0]

    # ── 현재가 조회 ──────────────────────────────────────

    async def get_price(self, symbol: str) -> dict:
        """선물 현재가 조회"""
        resp = await self._retry_call(self._get_price_raw, symbol)
        return resp if resp else {}

    async def _get_price_raw(self, symbol: str) -> dict:
        market = self.futures.market()
        resp = await market.o3105(
            body=O3105InBlock(symbol=symbol),
            options=_rate_opts,
        ).req_async()

        if resp.status_code >= 400:
            log.error("선물 현재가 조회 실패 %s: %s", symbol, resp.error_msg)
            return {}

        b = resp.block
        return {
            "symbol": b.Symbol,
            "name": b.SymbolNm,
            "price": float(b.TrdP),
            "open": float(b.OpenP),
            "high": float(b.HighP),
            "low": float(b.LowP),
            "prev_close": float(b.CloseP),
            "volume": int(b.TotQ),
            "rate": float(b.Diff),
            "tick_size": float(b.UntPrc),
            "tick_value": float(b.MnChgAmt),
            "opening_margin": float(b.OpngMgn),
            "expiry_date": b.MtrtDt,
        }

    # ── 일봉 차트 조회 ──────────────────────────────────

    async def get_daily_chart(self, symbol: str, start_date: str,
                              end_date: str, count: int = 100) -> list[dict]:
        """일봉 데이터 조회. start_date/end_date: YYYYMMDD"""
        chart = self.futures.chart()
        resp = await chart.o3108(
            body=O3108InBlock(
                shcode=symbol,
                gubun="0",  # 일봉
                qrycnt=count,
                sdate=start_date,
                edate=end_date,
                cts_date="",
            ),
            options=_rate_opts,
        ).req_async()

        if resp.status_code >= 400:
            log.error("선물 차트 조회 실패 %s: %s", symbol, resp.error_msg)
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

    # ── 예수금/증거금 조회 ───────────────────────────────

    async def get_balance(self) -> dict:
        """예수금/증거금/주문가능금액 조회"""
        resp = await self._retry_call(self._get_balance_raw)
        return resp if resp else {}

    async def _get_balance_raw(self) -> dict:
        accno = self.futures.accno()
        today = datetime.utcnow().strftime("%Y%m%d")
        resp = await accno.cidbq03000(
            body=CIDBQ03000InBlock1(RecCnt=1, AcntTpCode="1", TrdDt=today),
            options=_rate_opts,
        ).req_async()

        if resp.status_code >= 400:
            log.error("선물 예수금 조회 실패: %s", resp.error_msg)
            return {}

        result = {}
        if resp.block2:
            for item in resp.block2:
                result = {
                    "deposit": float(item.OvrsFutsDps),
                    "margin_used": float(item.AbrdFutsCsgnMgn),
                    "orderable": float(item.AbrdFutsOrdAbleAmt),
                    "eval_pnl": float(item.AbrdFutsEvalPnlAmt),
                    "eval_asset": float(item.EvalAssetAmt),
                    "withdrawable": float(item.AbrdFutsWthdwAbleAmt),
                }
                break
        return result

    # ── 미결제 잔고(포지션) 조회 ─────────────────────────

    async def get_holdings(self) -> list[dict]:
        """미결제 잔고(보유 포지션) 조회"""
        resp = await self._retry_call(self._get_holdings_raw)
        return resp if resp else []

    async def _get_holdings_raw(self) -> list[dict]:
        accno = self.futures.accno()
        today = datetime.utcnow().strftime("%Y%m%d")
        resp = await accno.cidbq01500(
            body=CIDBQ01500InBlock1(
                RecCnt=1, AcntTpCode="1", QryDt=today,
                BalTpCode="1", FcmAcntNo="",
            ),
            options=_rate_opts,
        ).req_async()

        if resp.status_code >= 400:
            log.error("선물 미결제잔고 조회 실패: %s", resp.error_msg)
            return []

        holdings = []
        if resp.block2:
            for item in resp.block2:
                qty = float(item.BalQty)
                if qty <= 0:
                    continue
                holdings.append({
                    "symbol": item.IsuCodeVal,
                    "name": item.IsuNm,
                    "direction": "LONG" if item.BnsTpCode == "2" else "SHORT",
                    "quantity": int(qty),
                    "entry_price": float(item.PchsPrc),
                    "current_price": float(item.OvrsDrvtNowPrc),
                    "eval_pnl": float(item.AbrdFutsEvalPnlAmt),
                    "expiry_date": item.DueDt,
                })
        return holdings

    # ── 주문 (신규) ──────────────────────────────────────

    async def place_order(self, symbol: str, quantity: int, price: float,
                          is_buy: bool, market_order: bool = False) -> dict:
        """신규 주문. 성공 시 {order_no} 반환"""
        resp = await self._retry_call(
            self._place_order_raw, symbol, quantity, price, is_buy, market_order,
        )
        return resp if resp else {}

    async def _place_order_raw(self, symbol: str, quantity: int, price: float,
                               is_buy: bool, market_order: bool = False) -> dict:
        order = self.futures.order()
        today = datetime.utcnow().strftime("%Y%m%d")
        resp = await order.cidbt00100(
            body=CIDBT00100InBlock1(
                RecCnt=1,
                OrdDt=today,
                IsuCodeVal=symbol,
                FutsOrdTpCode="1",                          # 1: 신규
                BnsTpCode="2" if is_buy else "1",            # 2: 매수, 1: 매도
                AbrdFutsOrdPtnCode="1" if market_order else "2",  # 1: 시장가, 2: 지정가
                CrcyCode="",
                OvrsDrvtOrdPrc=0.0 if market_order else price,
                CndiOrdPrc=0.0,
                OrdQty=quantity,
                PrdtCode="",
                DueYymm="",
                ExchCode="",
            ),
            options=_rate_opts,
        ).req_async()

        if resp.status_code >= 400:
            log.error("선물 주문 실패 %s: %s", symbol, resp.error_msg)
            return {}

        return {
            "order_no": str(resp.block2.OvrsFutsOrdNo),
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
                    log.error("%s 최종 실패 (%d회 시도): %s",
                              fn.__name__, max_retries, e)
                    return None
                delay = base_delay ** attempt
                log.warning("%s 재시도 %d/%d (%d초 후): %s",
                            fn.__name__, attempt, max_retries, delay, e)
                await asyncio.sleep(delay)
