"""리스크 관리 계산 단위 테스트"""
import pytest
import config


class TestRiskLossCalculation:
    """일일 손실률 계산: loss_pct = ((starting - current) / starting) * 100"""

    def _loss_pct(self, starting, current):
        if starting <= 0:
            return 0.0
        return ((starting - current) / starting) * 100

    def test_no_loss(self):
        assert self._loss_pct(100000, 100000) == 0.0

    def test_profit(self):
        """수익이면 음수 (청산 안 됨)"""
        assert self._loss_pct(100000, 110000) == -10.0

    def test_warn_threshold(self):
        """주식: 4% 손실"""
        loss = self._loss_pct(100000, 96000)
        assert loss == 4.0
        assert loss >= config.RISK_WARN_PCT

    def test_stop_threshold(self):
        """주식: 5% 손실"""
        loss = self._loss_pct(100000, 95000)
        assert loss == 5.0
        assert loss >= config.RISK_STOP_PCT

    def test_between_warn_and_stop(self):
        """4.5% → 경고만 (비상 아님)"""
        loss = self._loss_pct(100000, 95500)
        assert loss >= config.RISK_WARN_PCT
        assert loss < config.RISK_STOP_PCT

    def test_futures_warn_threshold(self):
        """선물: 3% 손실"""
        loss = self._loss_pct(100000, 97000)
        assert loss == 3.0
        assert loss >= config.FUTURES_RISK_WARN_PCT

    def test_futures_stop_threshold(self):
        """선물: 5% 손실"""
        loss = self._loss_pct(100000, 95000)
        assert loss >= config.FUTURES_RISK_STOP_PCT

    def test_zero_starting_balance(self):
        assert self._loss_pct(0, 10000) == 0.0


class TestMarginRateCalculation:
    """증거금 사용률: margin_rate = (margin_used / equity) * 100"""

    def _margin_rate(self, margin_used, equity):
        if equity <= 0:
            return 0.0
        return (margin_used / equity) * 100

    def test_no_margin(self):
        assert self._margin_rate(0, 100000) == 0.0

    def test_half_used(self):
        assert self._margin_rate(50000, 100000) == 50.0

    def test_at_limit(self):
        rate = self._margin_rate(80000, 100000)
        assert rate == 80.0
        assert rate >= config.FUTURES_MARGIN_LIMIT_PCT

    def test_over_limit(self):
        rate = self._margin_rate(90000, 100000)
        assert rate > config.FUTURES_MARGIN_LIMIT_PCT

    def test_under_limit(self):
        rate = self._margin_rate(70000, 100000)
        assert rate < config.FUTURES_MARGIN_LIMIT_PCT

    def test_zero_equity(self):
        assert self._margin_rate(50000, 0) == 0.0


class TestRiskThresholdConfig:
    """config 리스크 설정값 정합성"""

    def test_stock_warn_less_than_stop(self):
        assert config.RISK_WARN_PCT < config.RISK_STOP_PCT

    def test_futures_warn_less_than_stop(self):
        assert config.FUTURES_RISK_WARN_PCT < config.FUTURES_RISK_STOP_PCT

    def test_margin_limit_range(self):
        assert 0 < config.FUTURES_MARGIN_LIMIT_PCT <= 100

    def test_risk_per_trade_reasonable(self):
        assert 0 < config.FUTURES_RISK_PER_TRADE <= 10
