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
from web.api import router as api_router, set_scheduler, set_futures_scheduler

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


@asynccontextmanager
async def lifespan(app: FastAPI):
    """앱 시작/종료 시 봇 관리 (해외주식 + 해외선물)"""
    global futures_bot

    await init_db()
    log.info("데이터베이스 초기화 완료")

    # 해외주식 봇 시작
    await bot.start()
    set_scheduler(bot)

    # 해외선물 봇 시작 (텔레그램 공유)
    try:
        futures_bot = FuturesScheduler(notify_fn=bot.telegram.send)
        await futures_bot.start()
        set_futures_scheduler(futures_bot)
        log.info("해외선물 모의투자 봇 시작 완료")
    except Exception as e:
        log.error("해외선물 봇 시작 실패 (해외주식 봇은 정상 운영): %s", e)
        futures_bot = None

    yield

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
