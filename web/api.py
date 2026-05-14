"""웹 대시보드 API: FastAPI 라우터"""
import asyncio
import logging
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from fastapi import APIRouter

import config
from database import repository as repo

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api")
ET = ZoneInfo("America/New_York")
KST = ZoneInfo("Asia/Seoul")

# 스케줄러 참조 (main에서 주입)
_scheduler = None
_futures_scheduler = None
_krx_scheduler = None

# LS API 캐시 (TR별 분당 호출 제한 대응)
_cache = {"balance": {}, "holdings": [], "_balance_at": 0, "_holdings_at": 0}
_futures_cache = {"balance": {}, "holdings": [], "_balance_at": 0, "_holdings_at": 0}
_krx_cache = {"balance": {}, "holdings": [], "_balance_at": 0, "_holdings_at": 0}
CACHE_TTL = 30  # 30초 캐시


def set_scheduler(scheduler):
    global _scheduler
    _scheduler = scheduler


def set_futures_scheduler(scheduler):
    global _futures_scheduler
    _futures_scheduler = scheduler


def set_krx_scheduler(scheduler):
    global _krx_scheduler
    _krx_scheduler = scheduler


async def _get_cached_balance():
    now = time.time()
    if now - _cache["_balance_at"] < CACHE_TTL and _cache["balance"]:
        return _cache["balance"]
    try:
        _cache["balance"] = await _scheduler.client.get_balance()
        _cache["_balance_at"] = now
    except Exception as e:
        log.warning("예수금 조회 실패: %s", e)
    return _cache["balance"]


async def _get_cached_holdings():
    now = time.time()
    if now - _cache["_holdings_at"] < CACHE_TTL and _cache["holdings"]:
        return _cache["holdings"]
    try:
        _cache["holdings"] = await _scheduler.client.get_holdings()
        _cache["_holdings_at"] = now
    except Exception as e:
        log.warning("보유종목 조회 실패: %s", e)
    return _cache["holdings"]


@router.get("/status")
async def get_status():
    """봇 상태 + 예수금 + 보유종목"""
    settings = await repo.get_all_settings()
    now_et = datetime.now(ET).strftime("%Y-%m-%d %H:%M") + " (미국동부시간)"
    now_kst = datetime.now(KST).strftime("%Y-%m-%d %H:%M") + " (한국시간)"

    result = {
        "mode": settings.get("mode", config.DEFAULT_MODE),
        "trading_paused": settings.get("trading_paused") == "1",
        "risk_stopped": settings.get("risk_stopped") == "1",
        "time_et": now_et,
        "time_kst": now_kst,
        "bot_running": _scheduler is not None,
        "balance": {},
        "holdings": [],
    }

    if _scheduler and _scheduler.client:
        result["balance"] = await _get_cached_balance()
        result["holdings"] = await _get_cached_holdings()

    return result


@router.get("/settings")
async def get_settings():
    """전체 설정값"""
    return await repo.get_all_settings()


@router.post("/settings/{key}")
async def update_setting(key: str, value: str):
    """설정값 변경"""
    allowed = {
        "mode": lambda v: v in ("dry", "live"),
        "donchian_period": lambda v: v.isdigit() and 5 <= int(v) <= 100,
        "atr_multiplier": lambda v: _is_float(v) and 1.0 <= float(v) <= 10.0,
        "max_stocks": lambda v: v.isdigit() and 1 <= int(v) <= 20,
        "capital_ratio": lambda v: v.isdigit() and 10 <= int(v) <= 100,
    }

    if key not in allowed:
        return {"error": f"변경 불가: {key}"}
    if not allowed[key](value):
        return {"error": f"잘못된 값: {value}"}

    await repo.set_setting(key, value)
    return {"ok": True, "key": key, "value": value}


@router.post("/control/{action}")
async def control(action: str):
    """매매 제어: start, stop"""
    if action == "stop":
        await repo.set_setting("trading_paused", "1")
        return {"ok": True, "action": "매매 중단"}
    elif action == "start":
        await repo.set_setting("trading_paused", "0")
        return {"ok": True, "action": "매매 재개"}
    return {"error": f"알 수 없는 액션: {action}"}


@router.get("/trades")
async def get_trades():
    """오늘 매매 내역"""
    trades = await repo.get_today_trades()
    return {"trades": trades, "count": len(trades)}


@router.get("/positions")
async def get_positions():
    """현재 포지션"""
    positions = await repo.get_positions()
    return {"positions": positions, "count": len(positions)}


@router.get("/logs")
async def get_logs(lines: int = 50):
    """최근 로그"""
    try:
        with open("data/turtle.log", "r", encoding="utf-8") as f:
            all_lines = f.readlines()
            return {"logs": all_lines[-lines:]}
    except FileNotFoundError:
        return {"logs": []}


# ══ 선물 API ═══════════════════════════════════════════


async def _get_cached_futures_balance():
    now = time.time()
    if now - _futures_cache["_balance_at"] < CACHE_TTL and _futures_cache["balance"]:
        return _futures_cache["balance"]
    try:
        _futures_cache["balance"] = await _futures_scheduler.client.get_balance()
        _futures_cache["_balance_at"] = now
    except Exception as e:
        log.warning("[선물] 예수금 조회 실패: %s", e)
    return _futures_cache["balance"]


async def _get_cached_futures_holdings():
    now = time.time()
    if now - _futures_cache["_holdings_at"] < CACHE_TTL and _futures_cache["holdings"]:
        return _futures_cache["holdings"]
    try:
        _futures_cache["holdings"] = await _futures_scheduler.client.get_holdings()
        _futures_cache["_holdings_at"] = now
    except Exception as e:
        log.warning("[선물] 미결제잔고 조회 실패: %s", e)
    return _futures_cache["holdings"]


@router.get("/futures/status")
async def get_futures_status():
    """선물 봇 상태"""
    settings = await repo.get_all_settings()
    result = {
        "trading_paused": settings.get("futures_trading_paused") == "1",
        "risk_stopped": settings.get("futures_risk_stopped") == "1",
        "bot_running": _futures_scheduler is not None,
        "balance": {},
        "holdings": [],
    }
    if _futures_scheduler and _futures_scheduler.client:
        result["balance"] = await _get_cached_futures_balance()
        result["holdings"] = await _get_cached_futures_holdings()
    return result


@router.get("/futures/settings")
async def get_futures_settings():
    """선물 설정값"""
    settings = await repo.get_all_settings()
    return {k: v for k, v in settings.items() if k.startswith("futures_")}


@router.post("/futures/settings/{key}")
async def update_futures_setting(key: str, value: str):
    """선물 설정값 변경"""
    allowed = {
        "futures_donchian_period": lambda v: v.isdigit() and 5 <= int(v) <= 100,
        "futures_atr_multiplier": lambda v: _is_float(v) and 1.0 <= float(v) <= 10.0,
        "futures_max_contracts": lambda v: v.isdigit() and 1 <= int(v) <= 20,
        "futures_risk_per_trade": lambda v: _is_float(v) and 0.5 <= float(v) <= 10.0,
    }
    if key not in allowed:
        return {"error": f"변경 불가: {key}"}
    if not allowed[key](value):
        return {"error": f"잘못된 값: {value}"}
    await repo.set_setting(key, value)
    return {"ok": True, "key": key, "value": value}


@router.post("/futures/control/{action}")
async def futures_control(action: str):
    """선물 매매 제어"""
    if action == "stop":
        await repo.set_setting("futures_trading_paused", "1")
        return {"ok": True, "action": "선물 매매 중단"}
    elif action == "start":
        await repo.set_setting("futures_trading_paused", "0")
        return {"ok": True, "action": "선물 매매 재개"}
    return {"error": f"알 수 없는 액션: {action}"}


@router.get("/futures/trades")
async def get_futures_trades():
    """오늘 선물 매매 내역"""
    trades = await repo.get_today_futures_trades()
    return {"trades": trades, "count": len(trades)}


@router.get("/futures/positions")
async def get_futures_positions():
    """선물 포지션"""
    positions = await repo.get_futures_positions()
    return {"positions": positions, "count": len(positions)}


def _is_float(v: str) -> bool:
    try:
        float(v)
        return True
    except ValueError:
        return False


# ══ 일봉 차트 API ═══════════════════════════════════════════
# 종목별 5분 캐시 (LS API 호출 제한 보호)
_chart_cache: dict[str, tuple[float, list[dict]]] = {}
CHART_CACHE_TTL = 300  # 5분


def _clamp_days(days: int) -> int:
    return max(20, min(days, 400))


@router.get("/chart/stock")
async def get_stock_chart(symbol: str, exchange_code: str = "82", days: int = 120):
    """해외주식 일봉 차트. exchange_code: 81=NYSE, 82=NASDAQ"""
    if not _scheduler or not _scheduler.client:
        return {"error": "해외주식 봇이 실행 중이 아닙니다", "candles": []}
    symbol = symbol.strip().upper()
    if not symbol:
        return {"error": "종목 심볼이 비어 있습니다", "candles": []}

    days = _clamp_days(days)
    key = f"stock:{exchange_code}:{symbol}:{days}"
    now = time.time()
    cached = _chart_cache.get(key)
    if cached and now - cached[0] < CHART_CACHE_TTL:
        return {"symbol": symbol, "exchange_code": exchange_code,
                "candles": cached[1], "cached": True}

    today = datetime.now(ET).date()
    edate = today.strftime("%Y%m%d")
    sdate = (today - timedelta(days=days * 2)).strftime("%Y%m%d")  # 영업일 보정 위해 2배 폭

    try:
        candles = await _scheduler.client.get_daily_chart(
            symbol=symbol, exchange_code=exchange_code,
            start_date=sdate, end_date=edate, count=days,
        )
    except Exception as e:
        log.warning("주식 차트 조회 실패 %s: %s", symbol, e)
        return {"error": str(e), "candles": []}

    candles = sorted(candles, key=lambda c: c["date"])
    _chart_cache[key] = (now, candles)
    return {"symbol": symbol, "exchange_code": exchange_code,
            "candles": candles, "cached": False}


@router.get("/chart/futures/symbols")
async def get_futures_chart_symbols():
    """선물 차트 셀렉트용 종목 목록(기초상품 + 근월물 자동 매핑)"""
    items = []
    for sym in config.FUTURES_SYMBOLS:
        front = None
        if _futures_scheduler and _futures_scheduler.client:
            try:
                front = await _futures_scheduler.client.get_front_symbol(sym["base"])
            except Exception as e:
                log.warning("선물 근월물 조회 실패 %s: %s", sym["base"], e)
        items.append({
            "base": sym["base"],
            "name": sym["name"],
            "exchange": sym["exchange"],
            "front_symbol": front,
        })
    return {"symbols": items}


@router.get("/chart/futures")
async def get_futures_chart(symbol: str = "", base: str = "", days: int = 120):
    """해외선물 일봉 차트. symbol(만기포함) 또는 base(기초상품) 중 하나 필요"""
    if not _futures_scheduler or not _futures_scheduler.client:
        return {"error": "해외선물 봇이 실행 중이 아닙니다", "candles": []}

    symbol = symbol.strip().upper()
    base = base.strip().upper()

    # base만 들어오면 근월물 매핑
    if not symbol and base:
        try:
            symbol = await _futures_scheduler.client.get_front_symbol(base) or ""
        except Exception as e:
            log.warning("선물 근월물 조회 실패 %s: %s", base, e)
    if not symbol:
        return {"error": "종목 심볼을 찾을 수 없습니다", "candles": []}

    days = _clamp_days(days)
    key = f"futures:{symbol}:{days}"
    now = time.time()
    cached = _chart_cache.get(key)
    if cached and now - cached[0] < CHART_CACHE_TTL:
        return {"symbol": symbol, "candles": cached[1], "cached": True}

    today = datetime.now(KST).date()
    edate = today.strftime("%Y%m%d")
    sdate = (today - timedelta(days=days * 2)).strftime("%Y%m%d")

    try:
        candles = await _futures_scheduler.client.get_daily_chart(
            symbol=symbol, start_date=sdate, end_date=edate, count=days,
        )
    except Exception as e:
        log.warning("선물 차트 조회 실패 %s: %s", symbol, e)
        return {"error": str(e), "candles": []}

    candles = sorted(candles, key=lambda c: c["date"])
    _chart_cache[key] = (now, candles)
    return {"symbol": symbol, "candles": candles, "cached": False}


# ══ 국내주식 (KRX) API ═══════════════════════════════════════

async def _get_cached_krx_balance():
    now = time.time()
    if now - _krx_cache["_balance_at"] < CACHE_TTL and _krx_cache["balance"]:
        return _krx_cache["balance"]
    try:
        acc = await _krx_scheduler.client.get_account()
        _krx_cache["balance"] = acc.get("balance", {})
        _krx_cache["holdings"] = acc.get("holdings", [])
        _krx_cache["_balance_at"] = now
        _krx_cache["_holdings_at"] = now
    except Exception as e:
        log.warning("[국내] 계좌 조회 실패: %s", e)
    return _krx_cache["balance"]


async def _get_cached_krx_holdings():
    # 항상 balance와 함께 채워지므로 캐시 만료 시 balance를 트리거
    await _get_cached_krx_balance()
    return _krx_cache["holdings"]


@router.get("/krx/status")
async def get_krx_status():
    settings = await repo.get_all_settings()
    now_kst = datetime.now(KST).strftime("%Y-%m-%d %H:%M") + " (한국시간)"
    result = {
        "mode": settings.get("krx_mode", config.DEFAULT_MODE),
        "trading_paused": settings.get("krx_trading_paused") == "1",
        "risk_stopped": settings.get("krx_risk_stopped") == "1",
        "time_kst": now_kst,
        "bot_running": _krx_scheduler is not None,
        "balance": {},
        "holdings": [],
    }
    if _krx_scheduler and _krx_scheduler.client:
        result["balance"] = await _get_cached_krx_balance()
        result["holdings"] = await _get_cached_krx_holdings()
    return result


@router.get("/krx/settings")
async def get_krx_settings():
    settings = await repo.get_all_settings()
    return {k: v for k, v in settings.items() if k.startswith("krx_")}


@router.post("/krx/settings/{key}")
async def update_krx_setting(key: str, value: str):
    allowed = {
        "krx_mode": lambda v: v in ("dry", "live"),
        "krx_donchian_period": lambda v: v.isdigit() and 5 <= int(v) <= 100,
        "krx_atr_multiplier": lambda v: _is_float(v) and 1.0 <= float(v) <= 10.0,
        "krx_max_stocks": lambda v: v.isdigit() and 1 <= int(v) <= 20,
        "krx_capital_ratio": lambda v: v.isdigit() and 10 <= int(v) <= 100,
    }
    if key not in allowed:
        return {"error": f"변경 불가: {key}"}
    if not allowed[key](value):
        return {"error": f"잘못된 값: {value}"}
    await repo.set_setting(key, value)
    return {"ok": True, "key": key, "value": value}


@router.post("/krx/control/{action}")
async def krx_control(action: str):
    if action == "stop":
        await repo.set_setting("krx_trading_paused", "1")
        return {"ok": True, "action": "국내 매매 중단"}
    elif action == "start":
        await repo.set_setting("krx_trading_paused", "0")
        return {"ok": True, "action": "국내 매매 재개"}
    return {"error": f"알 수 없는 액션: {action}"}


@router.get("/krx/trades")
async def get_krx_trades():
    trades = await repo.get_today_krx_trades()
    return {"trades": trades, "count": len(trades)}


@router.get("/chart/krx")
async def get_krx_chart(symbol: str, days: int = 120):
    if not _krx_scheduler or not _krx_scheduler.client:
        return {"error": "국내주식 봇이 실행 중이 아닙니다", "candles": []}
    symbol = symbol.strip()
    if not symbol:
        return {"error": "종목 코드가 비어 있습니다", "candles": []}

    days = _clamp_days(days)
    key = f"krx:{symbol}:{days}"
    now = time.time()
    cached = _chart_cache.get(key)
    if cached and now - cached[0] < CHART_CACHE_TTL:
        return {"symbol": symbol, "candles": cached[1], "cached": True}

    today = datetime.now(KST).date()
    edate = today.strftime("%Y%m%d")
    try:
        candles = await _krx_scheduler.client.get_daily_chart(
            symbol=symbol, end_date=edate, count=days,
        )
    except Exception as e:
        log.warning("[국내] 차트 조회 실패 %s: %s", symbol, e)
        return {"error": str(e), "candles": []}

    candles = sorted(candles, key=lambda c: c["date"])
    _chart_cache[key] = (now, candles)
    return {"symbol": symbol, "candles": candles, "cached": False}


# ══ 통합 비교 / 벤치마크 ═══════════════════════════════════════

def _to_returns(reports: list[dict], value_key: str) -> list[dict]:
    """일일 리포트 → [{date, ret_pct}] — 일별 수익률 누적 곱셈.
    daily_pnl_rate가 채워져 있으면 우선 사용 (입출금 영향 제외된 정확한 수익률).
    없으면 ending_balance 비율로 폴백."""
    out = []
    cum = 1.0
    first = True
    prev_val = None
    for r in reports:
        v = r.get(value_key) or 0
        rate = r.get("daily_pnl_rate")
        if first:
            out.append({"date": r["report_date"], "value": v, "ret_pct": 0.0})
            cum = 1.0
            prev_val = v
            first = False
            continue
        if rate is not None and rate != 0:
            cum *= (1 + rate / 100)
        elif prev_val and v:
            cum *= (v / prev_val)
        out.append({
            "date": r["report_date"],
            "value": v,
            "ret_pct": (cum - 1) * 100,
        })
        prev_val = v or prev_val
    return out


def _kospi_series(days: int) -> list[dict]:
    """yfinance ^KS11 종가 → 시작일 대비 누적 수익률 (캐시 없음)"""
    import yfinance as yf
    from datetime import date

    end = date.today()
    start = end - timedelta(days=days + 14)  # 영업일 보정 여유
    try:
        hist = yf.Ticker("^KS11").history(start=start, end=end, interval="1d", auto_adjust=False)
    except Exception as e:
        log.warning("코스피 조회 실패: %s", e)
        return []
    if hist is None or hist.empty:
        return []

    rows = []
    base = None
    closes = hist["Close"]
    # 최근 days개만 사용
    if len(closes) > days:
        closes = closes.iloc[-days:]
    for idx, val in closes.items():
        if val is None:
            continue
        d = idx.strftime("%Y-%m-%d")
        v = float(val)
        if base is None:
            base = v
            rows.append({"date": d, "value": v, "ret_pct": 0.0})
        else:
            rows.append({"date": d, "value": v, "ret_pct": (v / base - 1) * 100})
    return rows


@router.get("/benchmark/kospi")
async def get_kospi(days: int = 30):
    """코스피지수(^KS11) 누적 수익률. 캐시 없음."""
    days = max(5, min(days, 365))
    series = await asyncio.to_thread(_kospi_series, days)
    return {"days": days, "series": series}


def _series_from_values(rows: list[dict], date_key: str, value_key: str) -> list[dict]:
    """LS API 시계열을 (시작일=0%) 누적수익률로 변환"""
    out = []
    base = None
    for r in rows:
        v = r.get(value_key) or 0
        d = r.get(date_key) or ""
        if not v:
            continue
        if base is None:
            base = v
            out.append({"date": d, "value": v, "ret_pct": 0.0})
        else:
            out.append({"date": d, "value": v, "ret_pct": (v / base - 1) * 100})
    return out


@router.get("/performance/compare")
async def compare_performance(days: int = 30):
    """누적 수익률 통합 차트.

    데이터 소스:
    - 국내주식: krx_daily_reports (KRX 스케줄러가 FOCCQ33600 시계열을 매일 백필)
    - 해외주식: daily_reports (해외주식 스케줄러가 매일 KST 16:10 + 봇 시작 시 스냅샷 저장)
    - 해외선물: futures_daily_reports (해외선물 스케줄러가 매일 KST 18:10 + 봇 시작 시 스냅샷 저장)
    - 코스피지수: yfinance ^KS11 (캐시 없음, 매 요청마다 새로 조회)

    "새로고침" 버튼이 강제 갱신을 원하면 ?refresh=1 옵션으로 LS API에서 오늘 스냅샷을 즉시 동기화한다.
    """
    days = max(5, min(days, 365))
    today_kst = datetime.now(KST).strftime("%Y-%m-%d")

    # 강제 새로고침: 모든 봇에서 오늘 스냅샷 LS API 즉시 가져와 DB upsert
    refresh_results = {}
    if _scheduler and _scheduler.client:
        try:
            s = await _scheduler.client.get_today_snapshot()
            v = s.get("won_eval_sum", 0)
            if v:
                await repo.upsert_daily_balance(today_kst, v)
                refresh_results["stock"] = v
        except Exception as e:
            log.warning("해외주식 즉시 스냅샷 실패: %s", e)
    if _futures_scheduler and _futures_scheduler.client:
        try:
            s = await _futures_scheduler.client.get_today_snapshot()
            v = s.get("eval_asset", 0)
            if v:
                await repo.upsert_futures_daily_equity(today_kst, v)
                refresh_results["futures"] = v
        except Exception as e:
            log.warning("해외선물 즉시 스냅샷 실패: %s", e)
    if _krx_scheduler and _krx_scheduler.client:
        try:
            rows = await _krx_scheduler.client.get_performance(max(days, 30))
            for r in rows:
                d = r.get("date", "")
                v = r.get("eval_amount", 0)
                if len(d) == 8 and v:
                    rd = f"{d[:4]}-{d[4:6]}-{d[6:8]}"
                    await repo.upsert_krx_daily_balance(rd, v)
            refresh_results["krx"] = len(rows)
        except Exception as e:
            log.warning("국내주식 즉시 시계열 실패: %s", e)

    # 시계열 읽기 (모든 시리즈는 daily_reports* 테이블 단일 소스)
    stock_rep = await repo.get_daily_reports(days)
    futures_rep = await repo.get_futures_daily_reports(days)
    krx_rep = await repo.get_krx_daily_reports(days)

    stock_series = _to_returns(stock_rep, "ending_balance")
    futures_series = _to_returns(futures_rep, "ending_equity")
    krx_series = _to_returns(krx_rep, "ending_balance")

    kospi = await asyncio.to_thread(_kospi_series, days)

    return {
        "days": days,
        "stock": stock_series,
        "futures": futures_series,
        "krx": krx_series,
        "kospi": kospi,
        "sources": {
            "stock": f"daily_reports ({len(stock_rep)}일)",
            "futures": f"futures_daily_reports ({len(futures_rep)}일)",
            "krx": f"krx_daily_reports ({len(krx_rep)}일)",
            "kospi": "yfinance ^KS11",
        },
        "refreshed": refresh_results,
    }


# ══ API 키 관리 ═══════════════════════════════════════════

_KEY_CATEGORIES = {
    "stock": {
        "appkey": "stock_appkey",
        "appsecretkey": "stock_appsecretkey",
        "config_appkey": "LS_APPKEY",
        "config_appsecretkey": "LS_APPSECRETKEY",
    },
    "futures_paper": {
        "appkey": "futures_paper_appkey",
        "appsecretkey": "futures_paper_appsecretkey",
        "config_appkey": "FUTURES_LS_APPKEY",
        "config_appsecretkey": "FUTURES_LS_APPSECRETKEY",
    },
    "futures_live": {
        "appkey": "futures_live_appkey",
        "appsecretkey": "futures_live_appsecretkey",
        "config_appkey": "FUTURES_LIVE_APPKEY",
        "config_appsecretkey": "FUTURES_LIVE_APPSECRETKEY",
    },
    "krx": {
        "appkey": "krx_appkey",
        "appsecretkey": "krx_appsecretkey",
        "config_appkey": "KRX_APPKEY",
        "config_appsecretkey": "KRX_APPSECRETKEY",
    },
}


def _mask(value: str) -> str:
    """키 값 마스킹 (앞4자리...뒤4자리)"""
    if not value or len(value) < 8:
        return ""
    return value[:4] + "..." + value[-4:]


@router.get("/keys")
async def get_keys():
    """API 키 상태 조회 (마스킹된 값)"""
    settings = await repo.get_all_settings()
    result = {}
    for category, keys in _KEY_CATEGORIES.items():
        db_appkey = settings.get(keys["appkey"], "")
        db_secret = settings.get(keys["appsecretkey"], "")
        # DB 값이 없으면 config(환경변수) 폴백
        appkey = db_appkey or getattr(config, keys["config_appkey"], "")
        secret = db_secret or getattr(config, keys["config_appsecretkey"], "")
        result[category] = {
            "appkey": _mask(appkey),
            "appsecretkey": _mask(secret),
            "has_key": bool(appkey),
            "has_secret": bool(secret),
            "source": "db" if db_appkey else ("env" if appkey else "none"),
        }
    return result


@router.post("/keys/{category}")
async def save_keys(category: str, appkey: str = "", appsecretkey: str = ""):
    """API 키 저장"""
    if category not in _KEY_CATEGORIES:
        return {"error": f"알 수 없는 카테고리: {category}"}

    keys = _KEY_CATEGORIES[category]
    saved = []

    if appkey:
        await repo.set_setting(keys["appkey"], appkey)
        setattr(config, keys["config_appkey"], appkey)
        saved.append("appkey")

    if appsecretkey:
        await repo.set_setting(keys["appsecretkey"], appsecretkey)
        setattr(config, keys["config_appsecretkey"], appsecretkey)
        saved.append("appsecretkey")

    if not saved:
        return {"error": "appkey 또는 appsecretkey를 입력해주세요"}

    log.info("[API키] %s 키 저장: %s", category, saved)
    return {"ok": True, "category": category, "saved": saved}
