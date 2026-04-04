"""trend_analyzer.py 단위 테스트 — 순수 계산 함수"""
import pytest
from analyzer.trend_analyzer import (
    calc_donchian, calc_atr, calc_moving_average, calc_momentum, analyze_trend,
)
from tests.conftest import make_candles, make_candles_ohlc


# ── calc_donchian ──────────────────────────────────────────

class TestCalcDonchian:
    def test_basic(self):
        candles = make_candles([10, 12, 15, 11, 13, 14, 16, 12, 11, 10])
        d = calc_donchian(candles, period=5)
        # 마지막 5개: [14, 16, 12, 11, 10] → high: 17, low: 9
        assert d["upper"] == 17.0  # 16 + 1.0
        assert d["lower"] == 9.0   # 10 - 1.0
        assert d["mid"] == (17.0 + 9.0) / 2

    def test_insufficient_data(self):
        candles = make_candles([10, 12, 15])
        assert calc_donchian(candles, period=5) == {}

    def test_exact_period_length(self):
        candles = make_candles([100, 110, 105, 115, 108])
        d = calc_donchian(candles, period=5)
        assert d["upper"] == 116.0  # 115 + 1.0
        assert d["lower"] == 99.0   # 100 - 1.0

    def test_constant_prices(self):
        candles = make_candles([50] * 20, spread=0)
        d = calc_donchian(candles, period=10)
        assert d["upper"] == 50.0
        assert d["lower"] == 50.0
        assert d["mid"] == 50.0


# ── calc_atr ───────────────────────────────────────────────

class TestCalcAtr:
    def test_basic(self):
        """일정 스프레드의 캔들 → ATR ≈ 스프레드"""
        candles = make_candles([100] * 25, spread=4.0)
        atr = calc_atr(candles, period=20)
        assert atr == pytest.approx(4.0, abs=0.01)

    def test_insufficient_data(self):
        candles = make_candles([100] * 10, spread=4.0)
        assert calc_atr(candles, period=20) == 0.0

    def test_with_gaps(self):
        """전일 종가와 갭이 있는 경우 True Range가 커야 함"""
        data = [
            (100, 102, 98, 100),  # day 0
            (100, 102, 98, 100),  # day 1: TR = max(4, 2, 2) = 4
            (110, 112, 108, 110), # day 2: gap up, TR = max(4, 12, 8) = 12
            (110, 112, 108, 110), # day 3: TR = 4
        ]
        candles = make_candles_ohlc(data)
        atr = calc_atr(candles, period=3)
        # TRs: [4, 12, 4] → avg = 6.67
        assert atr == pytest.approx(6.67, abs=0.01)

    def test_uses_last_n_periods(self):
        """ATR은 마지막 period개의 TR만 사용"""
        candles = make_candles([100] * 5 + [200] * 22, spread=10.0)
        atr = calc_atr(candles, period=20)
        # 마지막 20개 TR: 대부분 10, 하나만 gap 포함
        assert atr > 0


# ── calc_moving_average ────────────────────────────────────

class TestCalcMovingAverage:
    def test_basic(self):
        candles = make_candles([10, 20, 30, 40, 50])
        ma = calc_moving_average(candles, period=5)
        assert ma == pytest.approx(30.0)

    def test_period_3(self):
        candles = make_candles([10, 20, 30, 40, 50])
        ma = calc_moving_average(candles, period=3)
        assert ma == pytest.approx(40.0)  # (30+40+50)/3

    def test_insufficient_data(self):
        candles = make_candles([10, 20])
        assert calc_moving_average(candles, period=5) == 0.0


# ── calc_momentum ──────────────────────────────────────────

class TestCalcMomentum:
    def test_positive(self):
        candles = make_candles([100] * 50 + [120] * 12)
        mom = calc_momentum(candles, days=60)
        assert mom == pytest.approx(20.0)  # 100→120 = +20%

    def test_negative(self):
        candles = make_candles([100] * 50 + [80] * 12)
        mom = calc_momentum(candles, days=60)
        assert mom == pytest.approx(-20.0)

    def test_zero_base(self):
        candles = make_candles([0] * 62)
        assert calc_momentum(candles, days=60) == 0.0

    def test_insufficient_data(self):
        candles = make_candles([100] * 30)
        assert calc_momentum(candles, days=60) == 0.0


# ── analyze_trend ──────────────────────────────────────────

class TestAnalyzeTrend:
    def _uptrend_candles(self):
        """상승 추세: MA20 > MA60, 모멘텀 양수"""
        prices = list(range(100, 170))  # 70개: 100→169
        return make_candles(prices, spread=4.0)

    def _downtrend_candles(self):
        """하락 추세"""
        prices = list(range(170, 100, -1))  # 70개: 170→101
        return make_candles(prices, spread=4.0)

    def test_insufficient_data(self):
        candles = make_candles([100] * 30)
        assert analyze_trend(candles) == {}

    def test_uptrend_score(self):
        result = analyze_trend(self._uptrend_candles())
        assert result["trend_score"] > 50
        assert result["ma_short"] > result["ma_long"]

    def test_downtrend_score(self):
        result = analyze_trend(self._downtrend_candles())
        assert result["trend_score"] < 50
        assert result["ma_short"] < result["ma_long"]

    def test_has_all_fields(self):
        result = analyze_trend(self._uptrend_candles())
        expected_keys = {"donchian", "atr", "ma_short", "ma_long",
                         "momentum", "last_close", "trend_score", "is_breakout"}
        assert set(result.keys()) == expected_keys

    def test_breakout_detection(self):
        """돌파 판단: 현재가가 '직전 N봉'의 돈치안 상단 위.
        실제 엔진에서는 차트(과거 봉) + 현재가(별도 조회)로 비교하지만,
        analyze_trend은 마지막 봉 포함이므로 close > upper(=max high) 불가.
        → calc_donchian을 직전 봉 기준으로 분리 테스트."""
        prices = [100] * 70
        candles = make_candles(prices, spread=2.0)
        # 직전 20봉 기준 돈치안 (마지막 봉 제외)
        donchian = calc_donchian(candles[:-1], 20)
        current_price = 105.0  # 별도 현재가
        assert current_price > donchian["upper"]  # 105 > 101

    def test_no_breakout(self):
        """현재가가 돈치안 상단 이하면 breakout이 아님"""
        prices = [100] * 65 + [95, 96, 97, 98, 99]
        candles = make_candles(prices, spread=2.0)
        result = analyze_trend(candles, donchian_period=20)
        assert result["is_breakout"] is False
