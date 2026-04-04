"""웹 API 엔드포인트 테스트"""
import pytest
import pytest_asyncio
from unittest.mock import AsyncMock, patch
from httpx import AsyncClient, ASGITransport

import config
from database.models import init_db
from database import repository as repo


@pytest_asyncio.fixture
async def client(tmp_path):
    """테스트용 FastAPI 클라이언트 (스케줄러 없이)"""
    db_path = str(tmp_path / "test.db")
    original = config.DB_PATH
    config.DB_PATH = db_path
    await init_db()

    # 스케줄러 없이 API만 테스트
    from fastapi import FastAPI
    from web.api import router, set_scheduler, set_futures_scheduler
    app = FastAPI()
    app.include_router(router)
    set_scheduler(None)
    set_futures_scheduler(None)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    config.DB_PATH = original


@pytest.mark.asyncio
class TestSettingsAPI:
    async def test_get_settings(self, client):
        resp = await client.get("/api/settings")
        assert resp.status_code == 200
        data = resp.json()
        assert "donchian_period" in data

    async def test_update_valid_setting(self, client):
        resp = await client.post("/api/settings/donchian_period?value=25")
        assert resp.status_code == 200
        assert resp.json()["ok"] is True

        resp = await client.get("/api/settings")
        assert resp.json()["donchian_period"] == "25"

    async def test_update_invalid_key(self, client):
        resp = await client.post("/api/settings/invalid_key?value=123")
        assert resp.json().get("error")

    async def test_update_invalid_value(self, client):
        resp = await client.post("/api/settings/donchian_period?value=999")
        assert resp.json().get("error")


@pytest.mark.asyncio
class TestControlAPI:
    async def test_stop(self, client):
        resp = await client.post("/api/control/stop")
        assert resp.json()["ok"] is True

        settings = await repo.get_all_settings()
        assert settings["trading_paused"] == "1"

    async def test_start(self, client):
        await client.post("/api/control/stop")
        resp = await client.post("/api/control/start")
        assert resp.json()["ok"] is True

    async def test_invalid_action(self, client):
        resp = await client.post("/api/control/invalid")
        assert resp.json().get("error")


@pytest.mark.asyncio
class TestFuturesControlAPI:
    async def test_futures_stop(self, client):
        resp = await client.post("/api/futures/control/stop")
        assert resp.json()["ok"] is True

    async def test_futures_start(self, client):
        resp = await client.post("/api/futures/control/start")
        assert resp.json()["ok"] is True


@pytest.mark.asyncio
class TestFuturesSettingsAPI:
    async def test_get_futures_settings(self, client):
        resp = await client.get("/api/futures/settings")
        assert resp.status_code == 200
        data = resp.json()
        assert "futures_donchian_period" in data

    async def test_update_futures_setting(self, client):
        resp = await client.post("/api/futures/settings/futures_donchian_period?value=30")
        assert resp.json()["ok"] is True

    async def test_update_invalid_futures_setting(self, client):
        resp = await client.post("/api/futures/settings/invalid?value=30")
        assert resp.json().get("error")


@pytest.mark.asyncio
class TestKeysAPI:
    async def test_get_keys(self, client):
        resp = await client.get("/api/keys")
        assert resp.status_code == 200
        data = resp.json()
        assert "stock" in data
        assert "futures_paper" in data
        assert "futures_live" in data

    async def test_keys_are_masked(self, client):
        resp = await client.get("/api/keys")
        data = resp.json()
        for category in ["stock", "futures_paper"]:
            if data[category]["has_key"]:
                assert "..." in data[category]["appkey"]

    async def test_save_keys(self, client):
        resp = await client.post("/api/keys/stock?appkey=TESTKEY12345678&appsecretkey=TESTSECRET1234")
        assert resp.json()["ok"] is True
        assert "appkey" in resp.json()["saved"]
        assert "appsecretkey" in resp.json()["saved"]

    async def test_save_empty_keys(self, client):
        resp = await client.post("/api/keys/stock")
        assert resp.json().get("error")

    async def test_save_invalid_category(self, client):
        resp = await client.post("/api/keys/invalid?appkey=test")
        assert resp.json().get("error")


@pytest.mark.asyncio
class TestTradesAPI:
    async def test_get_trades_empty(self, client):
        resp = await client.get("/api/trades")
        assert resp.status_code == 200
        assert resp.json()["count"] == 0

    async def test_get_futures_trades_empty(self, client):
        resp = await client.get("/api/futures/trades")
        assert resp.status_code == 200
        assert resp.json()["count"] == 0
