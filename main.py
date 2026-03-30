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
from web.api import router as api_router, set_scheduler

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


@asynccontextmanager
async def lifespan(app: FastAPI):
    """앱 시작/종료 시 봇 관리"""
    await init_db()
    log.info("데이터베이스 초기화 완료")

    await bot.start()
    set_scheduler(bot)

    yield

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
