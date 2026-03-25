"""터틀 트레이딩 봇 시작점"""
import asyncio
import logging
import signal
import sys

from database.models import init_db
from scheduler import TurtleScheduler

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("data/turtle.log", encoding="utf-8"),
    ],
)
log = logging.getLogger(__name__)


async def main():
    # DB 초기화
    await init_db()
    log.info("데이터베이스 초기화 완료")

    # 스케줄러 시작
    bot = TurtleScheduler()
    await bot.start()

    # 종료 시그널 처리
    loop = asyncio.get_running_loop()
    stop_event = asyncio.Event()

    def _signal_handler():
        log.info("종료 신호 수신")
        stop_event.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, _signal_handler)

    # 무한 대기
    await stop_event.wait()

    # 정리
    await bot.stop()
    log.info("프로그램 종료")


if __name__ == "__main__":
    asyncio.run(main())
