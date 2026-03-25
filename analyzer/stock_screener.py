"""종목 스크리닝: 재무 필터 + 추세 분석 → 상위 N개 선정"""
import logging
from datetime import datetime, timedelta

import yfinance as yf

import config
from analyzer.trend_analyzer import analyze_trend
from database import repository as repo
from trader.ls_client import LSClient

log = logging.getLogger(__name__)


def _check_financials(ticker_symbol: str) -> dict | None:
    """yfinance로 재무 건전성 체크. 통과하면 점수 반환, 탈락하면 None"""
    try:
        tk = yf.Ticker(ticker_symbol)
        info = tk.info
        if not info:
            return None

        market_cap = info.get("marketCap", 0) or 0
        if market_cap < config.MIN_MARKET_CAP:
            return None

        pe = info.get("trailingPE") or info.get("forwardPE")
        if pe is None or pe < config.MIN_PER or pe > config.MAX_PER:
            return None

        debt_ratio = info.get("debtToEquity")
        if debt_ratio is not None and debt_ratio > config.MAX_DEBT_RATIO:
            return None

        operating_income = info.get("operatingIncome", 0) or 0
        if operating_income <= 0:
            return None

        # 재무 점수 (0~100)
        score = 0.0
        # PER 낮을수록 좋음 (0~30)
        score += max(0, 30 - (pe / config.MAX_PER * 30))
        # 부채비율 낮을수록 좋음 (0~30)
        if debt_ratio is not None:
            score += max(0, 30 - (debt_ratio / config.MAX_DEBT_RATIO * 30))
        else:
            score += 15
        # 시가총액 클수록 좋음 (0~20)
        cap_score = min(market_cap / 100_000_000_000, 1.0) * 20  # 1000억$ 이상 만점
        score += cap_score
        # 영업이익 (0~20)
        if operating_income > 1_000_000_000:
            score += 20
        elif operating_income > 100_000_000:
            score += 10

        return {
            "financial_score": round(score, 2),
            "market_cap": market_cap,
            "pe": pe,
            "debt_ratio": debt_ratio,
        }
    except Exception as e:
        log.debug("재무 조회 실패 %s: %s", ticker_symbol, e)
        return None


async def screen_stocks(client: LSClient, max_stocks: int = None) -> list[dict]:
    """종목 스크리닝 메인 로직
    1) LS증권에서 NYSE + NASDAQ 종목 리스트 수집
    2) 재무 필터링
    3) 추세 분석
    4) 상위 N개 선정 → DB 저장
    """
    max_stocks = max_stocks or config.MAX_STOCKS
    settings = await repo.get_all_settings()
    donchian_period = int(settings.get("donchian_period", config.DONCHIAN_PERIOD))

    end_date = datetime.utcnow().strftime("%Y%m%d")
    start_date = (datetime.utcnow() - timedelta(days=120)).strftime("%Y%m%d")

    # 1) 종목 리스트 수집
    log.info("종목 리스트 수집 시작...")
    all_stocks = []
    for excd in [config.EXCHANGE_NYSE, config.EXCHANGE_NASDAQ]:
        stocks = await client.get_stock_list(excd)
        all_stocks.extend(stocks)
    log.info("총 %d개 종목 수집", len(all_stocks))

    # 거래정지·시가총액 0 제외
    candidates = [s for s in all_stocks if not s["suspended"] and s["last_close"] > 0]
    log.info("기본 필터 후 %d개", len(candidates))

    # 2) 재무 필터링
    log.info("재무 필터링 시작...")
    passed = []
    for s in candidates:
        fin = _check_financials(s["symbol"])
        if fin:
            s.update(fin)
            passed.append(s)

    log.info("재무 필터 통과 %d개", len(passed))

    # 3) 추세 분석
    log.info("추세 분석 시작...")
    analyzed = []
    for s in passed:
        candles = await client.get_daily_chart(
            s["symbol"], s["exchange_code"], start_date, end_date
        )
        if len(candles) < config.MA_LONG + 1:
            continue

        trend = analyze_trend(candles, donchian_period, config.MA_SHORT, config.MA_LONG)
        if not trend:
            continue

        s["momentum_score"] = trend["trend_score"]
        s["atr"] = trend["atr"]
        s["donchian"] = trend["donchian"]
        s["is_breakout"] = trend["is_breakout"]
        s["last_close"] = trend["last_close"]
        # 종합 점수 = 추세(60%) + 재무(40%)
        s["total_score"] = round(s["momentum_score"] * 0.6 + s["financial_score"] * 0.4, 2)
        analyzed.append(s)

    log.info("추세 분석 완료 %d개", len(analyzed))

    # 4) 상위 N개 선정
    analyzed.sort(key=lambda x: x["total_score"], reverse=True)
    selected = analyzed[:max_stocks]

    # DB 저장
    rows = []
    for i, s in enumerate(analyzed):
        rows.append({
            "symbol": s["symbol"],
            "exchange_code": s["exchange_code"],
            "company_name": s.get("name_kr") or s.get("name_en", ""),
            "momentum_score": s["momentum_score"],
            "financial_score": s["financial_score"],
            "total_score": s["total_score"],
            "selected": 1 if i < max_stocks else 0,
        })
    await repo.save_analysis(rows)

    log.info("종목 선정 완료: %s", [s["symbol"] for s in selected])
    return selected
