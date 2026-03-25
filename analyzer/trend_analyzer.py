"""추세 분석 로직 (터틀 전략)"""


def calc_donchian(candles: list[dict], period: int) -> dict:
    """돈치안 채널 계산. candles는 날짜 오름차순."""
    if len(candles) < period:
        return {}
    recent = candles[-period:]
    highs = [c["high"] for c in recent]
    lows = [c["low"] for c in recent]
    return {
        "upper": max(highs),
        "lower": min(lows),
        "mid": (max(highs) + min(lows)) / 2,
    }


def calc_atr(candles: list[dict], period: int = 20) -> float:
    """ATR(Average True Range) 계산"""
    if len(candles) < period + 1:
        return 0.0
    trs = []
    for i in range(1, len(candles)):
        h = candles[i]["high"]
        l = candles[i]["low"]
        pc = candles[i - 1]["close"]
        tr = max(h - l, abs(h - pc), abs(l - pc))
        trs.append(tr)
    return sum(trs[-period:]) / period


def calc_moving_average(candles: list[dict], period: int) -> float:
    """단순 이동평균"""
    if len(candles) < period:
        return 0.0
    closes = [c["close"] for c in candles[-period:]]
    return sum(closes) / period


def calc_momentum(candles: list[dict], days: int = 60) -> float:
    """모멘텀(수익률 %). days일 전 대비 현재 종가 수익률"""
    if len(candles) < days + 1:
        return 0.0
    old = candles[-(days + 1)]["close"]
    now = candles[-1]["close"]
    if old == 0:
        return 0.0
    return ((now - old) / old) * 100


def analyze_trend(candles: list[dict], donchian_period: int = 20,
                  ma_short: int = 20, ma_long: int = 60) -> dict:
    """종합 추세 분석. 돈치안 채널, ATR, 이동평균, 모멘텀 점수 계산"""
    if len(candles) < ma_long + 1:
        return {}

    donchian = calc_donchian(candles, donchian_period)
    atr = calc_atr(candles, donchian_period)
    ma_s = calc_moving_average(candles, ma_short)
    ma_l = calc_moving_average(candles, ma_long)
    momentum = calc_momentum(candles, 60)
    last_close = candles[-1]["close"]

    # 추세 점수 계산 (0~100)
    score = 0.0

    # 1) 이동평균 골든크로스: 단기 > 장기 → +30
    if ma_s > ma_l:
        score += 30

    # 2) 모멘텀: 3개월 수익률 기반 (최대 +30)
    score += min(max(momentum, 0), 30)

    # 3) 돈치안 채널 상단 근접도 (최대 +20)
    if donchian["upper"] > 0:
        proximity = (last_close - donchian["lower"]) / (donchian["upper"] - donchian["lower"])
        score += min(proximity * 20, 20)

    # 4) ATR 대비 가격 비율 적절성 (변동성 ~2~5% → +20)
    if last_close > 0:
        atr_pct = (atr / last_close) * 100
        if 1.0 <= atr_pct <= 5.0:
            score += 20
        elif atr_pct < 1.0:
            score += 10  # 변동성 너무 낮음
        # 변동성 너무 높으면 +0

    return {
        "donchian": donchian,
        "atr": atr,
        "ma_short": ma_s,
        "ma_long": ma_l,
        "momentum": momentum,
        "last_close": last_close,
        "trend_score": round(score, 2),
        "is_breakout": last_close > donchian["upper"] if donchian else False,
    }
