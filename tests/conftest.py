"""공통 테스트 픽스처"""
import pytest


def make_candles(closes: list[float], spread: float = 2.0) -> list[dict]:
    """테스트용 캔들 데이터 생성.
    close 기준으로 high = close + spread/2, low = close - spread/2."""
    candles = []
    for i, c in enumerate(closes):
        candles.append({
            "date": f"2026-01-{i+1:02d}",
            "open": c,
            "high": c + spread / 2,
            "low": c - spread / 2,
            "close": c,
            "volume": 1000,
        })
    return candles


def make_candles_ohlc(data: list[tuple]) -> list[dict]:
    """(open, high, low, close) 튜플 리스트에서 캔들 생성"""
    candles = []
    for i, (o, h, l, c) in enumerate(data):
        candles.append({
            "date": f"2026-01-{i+1:02d}",
            "open": o,
            "high": h,
            "low": l,
            "close": c,
            "volume": 1000,
        })
    return candles
