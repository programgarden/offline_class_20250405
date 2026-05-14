"""국내주식 (KRX) 스케줄러 — 한국시간 KST 기준 09:00~15:30"""
import asyncio
import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

import config
from database import repository as repo
from trader.krx_client import KrxClient
from trader.krx_engine import KrxEngine

log = logging.getLogger(__name__)
KST = ZoneInfo("Asia/Seoul")


def _now_str() -> str:
    return f"한국시간 {datetime.now(KST).strftime('%H:%M')}"


class KrxScheduler:
    def __init__(self, notify_fn=None):
        self.client = KrxClient()
        self.notify = notify_fn or (lambda m: None)
        self.engine: KrxEngine | None = None
        self.scheduler = AsyncIOScheduler(timezone=KST)
        self._stop_lock = asyncio.Lock()
        self._starting_balance: float = 0
        self._universe: list[dict] = []

    async def start(self):
        try:
            await self.client.login()
        except Exception as e:
            log.error("[KRX] 로그인 실패 - 봇 비활성: %s", e)
            raise

        self.engine = KrxEngine(self.client, notify_fn=self.notify)
        self._universe = list(config.KRX_DEFAULT_UNIVERSE)

        self._setup_schedule()
        self.scheduler.start()
        log.info("[KRX] 봇 시작 (%s)", _now_str())
        await self.notify(f"[국내] 봇 시작 ({_now_str()})")

        # 봇 시작 직후 1회 시계열 백필
        asyncio.create_task(self._job_save_snapshot())

    def _setup_schedule(self):
        add = self.scheduler.add_job
        # 09:00 - 시작 잔고 기록
        add(self._job_market_open, CronTrigger(hour=9, minute=0, timezone=KST),
            id="krx_market_open")
        # 15:35 - 마감 정리 + 일일 리포트
        add(self._job_daily_report, CronTrigger(hour=15, minute=35, timezone=KST),
            id="krx_daily_report")
        # 09:05 ~ 15:20, 매수/스탑 체크
        add(self._job_check_buy, CronTrigger(hour="9-15", minute="*/15", timezone=KST),
            id="krx_check_buy")
        add(self._job_check_stops, CronTrigger(hour="9-15", minute="*/5", timezone=KST),
            id="krx_check_stops")
        # 15:40 - FOCCQ33600 시계열을 krx_daily_reports에 백필 저장
        add(self._job_save_snapshot, CronTrigger(hour=15, minute=40, timezone=KST),
            id="krx_save_snapshot")

    async def _job_market_open(self):
        try:
            bal = await self.client.get_balance()
            self._starting_balance = bal.get("total_asset", 0) or bal.get("deposit", 0)
            log.info("[KRX] 정규장 시작 (시작자산 %s원)", f"{self._starting_balance:,.0f}")
            await self.notify(f"[국내] 정규장 시작 (시작자산 {self._starting_balance:,.0f}원)")
        except Exception as e:
            log.exception("[KRX] 정규장 시작 처리 실패: %s", e)

    async def _job_check_buy(self):
        try:
            now = datetime.now(KST)
            if now.hour == 15 and now.minute > 20:
                return
            await self.engine.check_and_buy(self._universe)
        except Exception as e:
            log.exception("[KRX] 매수 체크 실패: %s", e)

    async def _job_check_stops(self):
        try:
            async with self._stop_lock:
                await self.engine.check_trailing_stops()
        except Exception as e:
            log.exception("[KRX] 스탑 체크 실패: %s", e)

    async def _job_save_snapshot(self):
        """FOCCQ33600 시계열을 krx_daily_reports에 백필.
        TermErnrat(LS가 계산한 일별 수익률)을 daily_pnl_rate로 저장 — 입출금 영향 제외된 정확한 수익률."""
        try:
            rows = await self.client.get_performance(days=90)
            saved = 0
            for r in rows:
                d = r.get("date", "")
                v = r.get("eval_amount", 0)
                rate = r.get("term_ern_rat", 0.0)
                if len(d) == 8 and v:
                    rd = f"{d[:4]}-{d[4:6]}-{d[6:8]}"
                    await repo.upsert_krx_daily_balance(rd, v, daily_pnl_rate=rate)
                    saved += 1
            if saved:
                log.info("[KRX] 시계열 스냅샷 저장 %d일 (TermErnrat 기반)", saved)
        except Exception as e:
            log.warning("[KRX] 스냅샷 저장 실패: %s", e)

    async def _job_daily_report(self):
        try:
            trades = await repo.get_today_krx_trades()
            positions = await repo.get_krx_positions()
            bal = await self.client.get_balance()
            ending = bal.get("total_asset", 0) or bal.get("deposit", 0)
            starting = self._starting_balance or ending
            pnl = ending - starting
            rate = (pnl / starting * 100) if starting else 0

            sells = [t for t in trades if t["order_type"] == "SELL"]
            wins = 0
            for s in sells:
                buy = await repo.get_last_krx_buy_price(s["symbol"])
                if buy and s["price"] > buy:
                    wins += 1

            report = {
                "report_date": datetime.now(KST).strftime("%Y-%m-%d"),
                "starting_balance": starting,
                "ending_balance": ending,
                "daily_pnl": pnl,
                "daily_pnl_rate": rate,
                "total_trades": len(trades),
                "winning_trades": wins,
                "losing_trades": len(sells) - wins,
                "risk_stop_triggered": int((await repo.get_setting("krx_risk_stopped")) == "1"),
            }
            await repo.save_krx_daily_report(report)
            await self.notify(
                f"[국내] 일일 리포트 ({_now_str()})\n"
                f"시작: {starting:,.0f}원 / 종료: {ending:,.0f}원\n"
                f"손익: {pnl:+,.0f}원 ({rate:+.2f}%)\n"
                f"매매 {report['total_trades']}건 (수익 {wins}, 손실 {len(sells)-wins})\n"
                f"보유 {len(positions)}종목"
            )
        except Exception as e:
            log.exception("[KRX] 일일 리포트 실패: %s", e)

    async def stop(self):
        try:
            self.scheduler.shutdown(wait=False)
        except Exception:
            pass
        log.info("[KRX] 봇 종료")
