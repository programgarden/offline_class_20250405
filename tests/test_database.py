"""데이터베이스 CRUD 통합 테스트"""
import pytest
import pytest_asyncio
import aiosqlite
import os
import tempfile

import config
from database.models import init_db
from database import repository as repo


@pytest_asyncio.fixture
async def test_db(tmp_path):
    """임시 DB로 테스트"""
    db_path = str(tmp_path / "test.db")
    original = config.DB_PATH
    config.DB_PATH = db_path
    await init_db()
    yield db_path
    config.DB_PATH = original


@pytest.mark.asyncio
class TestSettings:
    async def test_get_default_settings(self, test_db):
        settings = await repo.get_all_settings()
        assert settings["mode"] == "dry"
        assert settings["donchian_period"] == "20"
        assert settings["atr_multiplier"] == "3.0"

    async def test_set_and_get_setting(self, test_db):
        await repo.set_setting("donchian_period", "30")
        val = await repo.get_setting("donchian_period")
        assert val == "30"

    async def test_upsert_new_key(self, test_db):
        """존재하지 않는 키도 INSERT 가능 (upsert)"""
        await repo.set_setting("stock_appkey", "test_key_123")
        val = await repo.get_setting("stock_appkey")
        assert val == "test_key_123"

    async def test_upsert_overwrite(self, test_db):
        await repo.set_setting("stock_appkey", "first")
        await repo.set_setting("stock_appkey", "second")
        val = await repo.get_setting("stock_appkey")
        assert val == "second"

    async def test_get_nonexistent(self, test_db):
        val = await repo.get_setting("does_not_exist")
        assert val is None


@pytest.mark.asyncio
class TestFuturesSettings:
    async def test_default_futures_settings(self, test_db):
        settings = await repo.get_all_settings()
        assert settings.get("futures_donchian_period") == "20"
        assert settings.get("futures_atr_multiplier") == "3.0"
        assert settings.get("futures_max_contracts") == "5"
        assert settings.get("futures_risk_per_trade") == "2.0"

    async def test_modify_futures_setting(self, test_db):
        await repo.set_setting("futures_donchian_period", "25")
        val = await repo.get_setting("futures_donchian_period")
        assert val == "25"


@pytest.mark.asyncio
class TestPositions:
    async def test_save_and_get_position(self, test_db):
        await repo.upsert_position(
            symbol="AAPL", exchange_code="82",
            quantity=10, avg_buy_price=150.0,
            highest_price=155.0, trailing_stop_price=140.0,
            atr=5.0, entry_date="2026-01-15",
        )
        positions = await repo.get_positions()
        assert len(positions) == 1
        assert positions[0]["symbol"] == "AAPL"
        assert positions[0]["quantity"] == 10

    async def test_delete_position(self, test_db):
        await repo.upsert_position(
            symbol="AAPL", exchange_code="82",
            quantity=10, avg_buy_price=150.0,
            highest_price=155.0, trailing_stop_price=140.0,
            atr=5.0, entry_date="2026-01-15",
        )
        await repo.delete_position("AAPL")
        positions = await repo.get_positions()
        assert len(positions) == 0


@pytest.mark.asyncio
class TestFuturesPositions:
    async def test_save_and_get(self, test_db):
        await repo.upsert_futures_position(
            symbol="HMHH26", base_symbol="HMH",
            direction="LONG", quantity=2,
            avg_entry_price=20000.0, highest_price=20100.0,
            lowest_price=19900.0, trailing_stop_price=19100.0,
            atr=300.0, tick_size=1.0, tick_value=10.0,
            entry_date="2026-01-15",
        )
        positions = await repo.get_futures_positions()
        assert len(positions) == 1
        p = positions[0]
        assert p["symbol"] == "HMHH26"
        assert p["base_symbol"] == "HMH"
        assert p["direction"] == "LONG"
        assert p["quantity"] == 2

    async def test_delete_futures_position(self, test_db):
        await repo.upsert_futures_position(
            symbol="HMHH26", base_symbol="HMH",
            direction="LONG", quantity=1,
            avg_entry_price=20000.0, highest_price=20000.0,
            lowest_price=20000.0, trailing_stop_price=19100.0,
            atr=300.0, tick_size=1.0, tick_value=10.0,
            entry_date="2026-01-15",
        )
        await repo.delete_futures_position("HMHH26")
        assert len(await repo.get_futures_positions()) == 0


@pytest.mark.asyncio
class TestTrades:
    async def test_save_stock_trade(self, test_db):
        await repo.save_trade(
            symbol="AAPL", exchange_code="82",
            order_type="BUY", order_no="123",
            quantity=10, price=150.0,
            reason="ENTRY", is_dry_run=True,
        )
        trades = await repo.get_today_trades()
        assert len(trades) == 1
        assert trades[0]["symbol"] == "AAPL"
        assert trades[0]["order_type"] == "BUY"

    async def test_save_futures_trade(self, test_db):
        await repo.save_futures_trade(
            symbol="HMHH26", base_symbol="HMH",
            direction="LONG", order_type="ENTRY",
            order_no="F001", quantity=2,
            price=20000.0, pnl=None, reason="ENTRY",
        )
        trades = await repo.get_today_futures_trades()
        assert len(trades) == 1
        assert trades[0]["symbol"] == "HMHH26"
        assert trades[0]["direction"] == "LONG"
