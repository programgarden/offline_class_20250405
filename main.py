"""터틀 트레이딩 봇 시작점 (FastAPI 웹 대시보드 통합)"""
import asyncio
import logging
import signal
import sys
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from fastapi import FastAPI
from fastapi.responses import FileResponse

# data 디렉터리 자동 생성 (로그, DB 저장용)
Path(__file__).parent.joinpath("data").mkdir(exist_ok=True)

from database.models import init_db
from scheduler import TurtleScheduler
from futures_scheduler import FuturesScheduler
from krx_scheduler import KrxScheduler
from web.api import (
    router as api_router,
    set_scheduler,
    set_futures_scheduler,
    set_krx_scheduler,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("data/turtle.log", encoding="utf-8"),
    ],
)
log = logging.getLogger(__name__)

bot = TurtleScheduler()
futures_bot: FuturesScheduler | None = None
krx_bot: KrxScheduler | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """앱 시작/종료 시 봇 관리 (해외주식 + 해외선물 + 국내주식)"""
    global futures_bot, krx_bot

    await init_db()
    log.info("데이터베이스 초기화 완료")

    # DB에 저장된 API 키가 있으면 config에 반영
    from database import repository as repo
    settings = await repo.get_all_settings()
    _key_map = {
        "stock_appkey": "LS_APPKEY",
        "stock_appsecretkey": "LS_APPSECRETKEY",
        "futures_paper_appkey": "FUTURES_LS_APPKEY",
        "futures_paper_appsecretkey": "FUTURES_LS_APPSECRETKEY",
        "futures_live_appkey": "FUTURES_LIVE_APPKEY",
        "futures_live_appsecretkey": "FUTURES_LIVE_APPSECRETKEY",
        "krx_appkey": "KRX_APPKEY",
        "krx_appsecretkey": "KRX_APPSECRETKEY",
    }
    for db_key, cfg_attr in _key_map.items():
        if settings.get(db_key):
            setattr(config, cfg_attr, settings[db_key])
            log.info("DB에서 API 키 로드: %s", db_key)

    # 해외주식 봇 시작
    await bot.start()
    set_scheduler(bot)

    # 해외선물 봇 시작 (텔레그램 공유, 30초 타임아웃)
    try:
        futures_bot = FuturesScheduler(notify_fn=bot.telegram.send)
        await asyncio.wait_for(futures_bot.start(), timeout=30)
        set_futures_scheduler(futures_bot)
        log.info("해외선물 모의투자 봇 시작 완료")
    except Exception as e:
        log.error("해외선물 봇 시작 실패 (해외주식 봇은 정상 운영): %s", e)
        futures_bot = None

    # 국내주식 봇 시작 (실패해도 다른 봇은 정상 운영)
    try:
        krx_bot = KrxScheduler(notify_fn=bot.telegram.send)
        await asyncio.wait_for(krx_bot.start(), timeout=30)
        set_krx_scheduler(krx_bot)
        log.info("국내주식 봇 시작 완료")
    except Exception as e:
        log.error("국내주식 봇 시작 실패 (다른 봇은 정상 운영): %s", e)
        krx_bot = None

    yield

    if krx_bot:
        await krx_bot.stop()
    if futures_bot:
        await futures_bot.stop()
    await bot.stop()
    log.info("프로그램 종료")


app = FastAPI(title="Turtle Trading Bot", lifespan=lifespan)
app.include_router(api_router)

DASHBOARD = Path(__file__).parent / "web" / "dashboard.html"


@app.get("/")
async def index():
    return FileResponse(DASHBOARD, media_type="text/html")


if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        log_level="info",
    )
