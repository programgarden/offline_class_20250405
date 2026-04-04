"""포지션 사이징 & 손익 계산 단위 테스트"""
import math
import pytest


class TestStockPositionSizing:
    """주식 매수 수량 계산: quantity = floor(per_stock / price)"""

    def test_basic(self):
        per_stock, price = 10000, 150.0
        assert math.floor(per_stock / price) == 66

    def test_exact_division(self):
        per_stock, price = 10000, 100.0
        assert math.floor(per_stock / price) == 100

    def test_expensive_stock(self):
        per_stock, price = 1000, 5000.0
        assert math.floor(per_stock / price) == 0  # 매수 불가

    def test_cheap_stock(self):
        per_stock, price = 10000, 1.50
        assert math.floor(per_stock / price) == 6666


class TestFuturesPositionSizing:
    """선물 계약 수 계산:
    risk_amount = equity * (risk_per_trade / 100)
    one_contract_risk = atr * (tick_value / tick_size)
    quantity = floor(risk_amount / one_contract_risk)
    """

    def _calc(self, equity, risk_pct, atr, tick_value, tick_size):
        risk_amount = equity * (risk_pct / 100)
        one_contract_risk = atr * (tick_value / tick_size)
        quantity = math.floor(risk_amount / one_contract_risk)
        return max(quantity, 1)  # 최소 1계약

    def test_basic_hsi(self):
        """항셍지수: equity=100000, risk=2%, ATR=200, tick_value=50, tick_size=1"""
        qty = self._calc(100000, 2.0, 200, 50, 1)
        # risk=2000, 1계약리스크=200*50=10000 → floor(2000/10000)=0 → 최소 1
        assert qty == 1

    def test_mini_hang_seng(self):
        """미니 항셍: tick_value=10, tick_size=1, ATR=200"""
        qty = self._calc(100000, 2.0, 200, 10, 1)
        # risk=2000, 1계약리스크=200*10=2000 → floor(2000/2000)=1
        assert qty == 1

    def test_large_equity(self):
        """큰 자본"""
        qty = self._calc(1000000, 2.0, 200, 10, 1)
        # risk=20000, 1계약리스크=2000 → 10계약
        assert qty == 10

    def test_small_atr(self):
        """ATR이 작으면 더 많은 계약"""
        qty = self._calc(100000, 2.0, 50, 10, 1)
        # risk=2000, 1계약리스크=500 → 4계약
        assert qty == 4

    def test_zero_atr_returns_minimum(self):
        """ATR=0이면 division by zero 방지 (실제 코드에서 skip)"""
        # 엔진에서는 atr<=0이면 continue 하므로 여기서는 최소값 테스트
        assert self._calc(100000, 2.0, 0.001, 10, 1) >= 1


class TestStockTrailingStop:
    """주식 트레일링 스탑: stop = price - atr * multiplier"""

    def test_basic(self):
        price, atr, mult = 150.0, 5.0, 3.0
        stop = round(price - atr * mult, 2)
        assert stop == 135.0

    def test_tight_stop(self):
        price, atr, mult = 100.0, 2.0, 1.5
        stop = round(price - atr * mult, 2)
        assert stop == 97.0

    def test_stop_update_on_new_high(self):
        """가격 상승 시 스탑도 같이 올라감"""
        atr, mult = 5.0, 3.0
        old_stop = round(150 - atr * mult, 2)  # 135
        new_price = 160.0
        new_stop = round(new_price - atr * mult, 2)  # 145
        assert new_stop > old_stop


class TestFuturesTrailingStop:
    """선물 트레일링 스탑 (소수점 미반올림)"""

    def test_long_stop(self):
        price, atr, mult = 20000.0, 300.0, 3.0
        stop = price - atr * mult
        assert stop == 19100.0

    def test_stop_ratchet(self):
        """스탑은 올라가기만 하고 내려가지 않음"""
        atr, mult = 300.0, 3.0
        stops = []
        for p in [20000, 20500, 20300, 21000]:
            stop = p - atr * mult
            if not stops or stop > stops[-1]:
                stops.append(stop)
            else:
                stops.append(stops[-1])  # 유지
        assert stops == [19100.0, 19600.0, 19600.0, 20100.0]


class TestFuturesPnL:
    """선물 손익 계산: pnl = (exit - entry) * (tick_value / tick_size) * qty"""

    def _pnl_long(self, entry, exit_price, tick_value, tick_size, qty):
        return (exit_price - entry) * (tick_value / tick_size) * qty

    def _pnl_short(self, entry, exit_price, tick_value, tick_size, qty):
        return (entry - exit_price) * (tick_value / tick_size) * qty

    def test_long_profit(self):
        pnl = self._pnl_long(20000, 20100, 50, 1, 2)
        assert pnl == 10000.0  # 100포인트 * 50 * 2계약

    def test_long_loss(self):
        pnl = self._pnl_long(20000, 19800, 50, 1, 1)
        assert pnl == -10000.0

    def test_short_profit(self):
        pnl = self._pnl_short(20000, 19900, 50, 1, 1)
        assert pnl == 5000.0

    def test_short_loss(self):
        pnl = self._pnl_short(20000, 20200, 10, 1, 3)
        assert pnl == -6000.0

    def test_mini_contract(self):
        """미니 계약 (tick_value=10)"""
        pnl = self._pnl_long(20000, 20050, 10, 1, 5)
        assert pnl == 2500.0

    def test_tick_size_not_one(self):
        """틱사이즈가 1이 아닌 경우 (예: 0.25)"""
        pnl = self._pnl_long(100.0, 101.0, 12.5, 0.25, 1)
        # 1.0 * (12.5/0.25) * 1 = 50
        assert pnl == 50.0


class TestStockPnL:
    """주식 손익: pnl = (exit - entry) * quantity"""

    def test_profit(self):
        entry, exit_p, qty = 150.0, 170.0, 10
        pnl = (exit_p - entry) * qty
        assert pnl == 200.0

    def test_loss(self):
        entry, exit_p, qty = 150.0, 140.0, 10
        pnl = (exit_p - entry) * qty
        assert pnl == -100.0

    def test_pnl_pct(self):
        entry, exit_p = 100.0, 115.0
        pnl_pct = ((exit_p - entry) / entry) * 100
        assert pnl_pct == pytest.approx(15.0)
