"""futures_client.py 단위 테스트 — 근월물 심볼 생성 (순수 함수)"""
import pytest
from datetime import date
from trader.futures_client import get_front_month_symbol


class TestGetFrontMonthSymbol:
    """분기 및 월간 만기 심볼 생성 테스트"""

    # ── 분기물 (quarterly=True): 3, 6, 9, 12월 ──

    def test_quarterly_jan(self):
        """1월 → 다음 만기 3월(H)"""
        assert get_front_month_symbol("HMH", quarterly=True, ref_date=date(2026, 1, 15)) == "HMHH26"

    def test_quarterly_mar(self):
        """3월 → 다음 만기 6월(M)"""
        assert get_front_month_symbol("HMH", quarterly=True, ref_date=date(2026, 3, 15)) == "HMHM26"

    def test_quarterly_jun(self):
        """6월 → 다음 만기 9월(U)"""
        assert get_front_month_symbol("HMH", quarterly=True, ref_date=date(2026, 6, 10)) == "HMHU26"

    def test_quarterly_sep(self):
        """9월 → 다음 만기 12월(Z)"""
        assert get_front_month_symbol("HMH", quarterly=True, ref_date=date(2026, 9, 20)) == "HMHZ26"

    def test_quarterly_dec_wraps_to_next_year(self):
        """12월 → 다음해 3월(H)"""
        assert get_front_month_symbol("HMH", quarterly=True, ref_date=date(2026, 12, 1)) == "HMHH27"

    def test_quarterly_nov(self):
        """11월 → 12월(Z)"""
        assert get_front_month_symbol("HMCE", quarterly=True, ref_date=date(2026, 11, 5)) == "HMCEZ26"

    # ── 월물 (quarterly=False): 매월 ──

    def test_monthly_jan(self):
        """1월 → 2월(G)"""
        assert get_front_month_symbol("HSI", quarterly=False, ref_date=date(2026, 1, 20)) == "HSIG26"

    def test_monthly_jul(self):
        """7월 → 8월(Q)"""
        assert get_front_month_symbol("HSI", quarterly=False, ref_date=date(2026, 7, 15)) == "HSIQ26"

    def test_monthly_dec_wraps(self):
        """12월 → 다음해 1월(F)"""
        assert get_front_month_symbol("HSI", quarterly=False, ref_date=date(2026, 12, 10)) == "HSIF27"

    def test_monthly_nov(self):
        """11월 → 12월(Z)"""
        assert get_front_month_symbol("MCA", quarterly=False, ref_date=date(2026, 11, 1)) == "MCAZ26"

    # ── 다양한 기초상품 ──

    def test_different_base_symbols(self):
        ref = date(2026, 4, 1)
        assert get_front_month_symbol("HMH", quarterly=True, ref_date=ref) == "HMHM26"
        assert get_front_month_symbol("HMCE", quarterly=True, ref_date=ref) == "HMCEM26"
        assert get_front_month_symbol("HSI", quarterly=False, ref_date=ref) == "HSIK26"

    # ── 연도 전환 ──

    def test_year_boundary(self):
        assert get_front_month_symbol("HMH", quarterly=True, ref_date=date(2027, 12, 25)) == "HMHH28"
        assert get_front_month_symbol("HSI", quarterly=False, ref_date=date(2029, 12, 1)) == "HSIF30"
