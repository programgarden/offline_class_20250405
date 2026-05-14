"""선물 스케줄러: 홍콩거래소 (HKEX) 시간 기준
T세션: 09:15~12:00, 13:00~16:30 HKT
T+1세션(야간): 17:15~03:00 HKT
"""
import asyncio
import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from database import repository as repo
from risk.futures_risk import FuturesRiskManager
from trader.futures_client import FuturesClient
from trader.futures_engine import FuturesEngine
from trader.futures_realtime import FuturesRealtimeMonitor

log = logging.getLogger(__name__)
HKT = ZoneInfo("Asia/Hong_Kong")
KST = ZoneInfo("Asia/Seoul")


def _now_str() -> str:
    kst = datetime.now(KST).strftime("%H:%M")
    hkt = datetime.now(HKT).strftime("%H:%M")
    return f"한국시간 {kst} / 홍콩시간 {hkt}"


class FuturesScheduler:
    def __init__(self, notify_fn=None):
        self.client = FuturesClient()
        self.notify = notify_fn or (lambda msg: None)
        self.engine: FuturesEngine | None = None
        self.risk: FuturesRiskManager | None = None
        self.realtime: FuturesRealtimeMonitor | None = None
        self.scheduler = AsyncIOScheduler(timezone=HKT)
        self._target_symbols: list[dict] = []
        self._stop_lock = asyncio.Lock()

    async def start(self):
        """선물 시스템 시작"""
        try:
            await self.client.login()
        except Exception as e:
            log.critical("[선물] 로그인 실패 - 선물 시스템 시작 불가: %s", e)
            raise

        self.engine = FuturesEngine(
            self.client,
            notify_fn=self.notify,
            on_buy_fn=self._on_new_buy,
        )
        self.risk = FuturesRiskManager(
            self.client, self.engine, notify_fn=self.notify,
        )
        self.realtime = FuturesRealtimeMonitor(
            self.client, on_price_update=self._on_realtime_price,
        )

        # 거래 대상 심볼 준비 (근월물 + 스펙)
        self._target_symbols = await self.engine.prepare_symbols()
        if self._target_symbols:
            symbols = [s["symbol"] for s in self._target_symbols]
            log.info("[선물] 거래 대상: %s", symbols)

        self._setup_schedule()
        self.scheduler.start()

        msg = f"[선물] 모의투자 봇 시작 ({_now_str()})"
        log.info(msg)
        await self.notify(msg)

        # 봇 시작 직후 1회 스냅샷 저장
        asyncio.create_task(self._job_save_snapshot())

    def _setup_schedule(self):
        """스케줄 등록 (홍콩시간 HKT 기준)
        T세션: 09:15~12:00, 13:00~16:30 HKT
        T+1세션(야간): 17:15~03:00 HKT (다음날)
        """
        add = self.scheduler.add_job

        # ── 세션 관리 ────────────────────────────────────
        # 09:10 HKT - T세션 시작 직전: 잔고 기록 + 실시간 연결
        add(self._job_session_open,
            CronTrigger(hour=9, minute=10, day_of_week="mon-fri", timezone=HKT),
            id="futures_session_open")

        # 03:05 HKT - T+1세션 마감 후: 리포트 생성
        add(self._job_daily_report,
            CronTrigger(hour=3, minute=5, day_of_week="tue-sat", timezone=HKT),
            id="futures_daily_report")

        # 03:10 HKT - 실시간 종료 + 리스크 초기화
        add(self._job_session_close,
            CronTrigger(hour=3, minute=10, day_of_week="tue-sat", timezone=HKT),
            id="futures_session_close")

        # ── T세션 (09:15~12:00, 13:00~16:30 HKT) ────────
        # 매수 체크 (15분 간격)
        add(self._job_check_buy,
            CronTrigger(hour="9-11", minute="*/15", day_of_week="mon-fri", timezone=HKT),
            id="futures_buy_t1")
        add(self._job_check_buy,
            CronTrigger(hour="13-16", minute="*/15", day_of_week="mon-fri", timezone=HKT),
            id="futures_buy_t2")

        # 트레일링 스탑 체크 (5분 간격)
        add(self._job_check_stops,
            CronTrigger(hour="9-11", minute="*/5", day_of_week="mon-fri", timezone=HKT),
            id="futures_stops_t1")
        add(self._job_check_stops,
            CronTrigger(hour="13-16", minute="*/5", day_of_week="mon-fri", timezone=HKT),
            id="futures_stops_t2")

        # 리스크 체크 (1분 간격)
        add(self._job_check_risk,
            CronTrigger(hour="9-11", minute="*", day_of_week="mon-fri", timezone=HKT),
            id="futures_risk_t1")
        add(self._job_check_risk,
            CronTrigger(hour="13-16", minute="*", day_of_week="mon-fri", timezone=HKT),
            id="futures_risk_t2")

        # ── T+1세션 야간 (17:15~03:00 HKT) ──────────────
        # 매수 체크 (15분 간격)
        add(self._job_check_buy,
            CronTrigger(hour="17-23", minute="*/15", day_of_week="mon-fri", timezone=HKT),
            id="futures_buy_night1")
        add(self._job_check_buy,
            CronTrigger(hour="0-2", minute="*/15", day_of_week="tue-sat", timezone=HKT),
            id="futures_buy_night2")

        # 트레일링 스탑 체크 (5분 간격)
        add(self._job_check_stops,
            CronTrigger(hour="17-23", minute="*/5", day_of_week="mon-fri", timezone=HKT),
            id="futures_stops_night1")
        add(self._job_check_stops,
            CronTrigger(hour="0-2", minute="*/5", day_of_week="tue-sat", timezone=HKT),
            id="futures_stops_night2")

        # 리스크 체크 (1분 간격)
        add(self._job_check_risk,
            CronTrigger(hour="17-23", minute="*", day_of_week="mon-fri", timezone=HKT),
            id="futures_risk_night1")
        add(self._job_check_risk,
            CronTrigger(hour="0-2", minute="*", day_of_week="tue-sat", timezone=HKT),
            id="futures_risk_night2")

        # ── 유지보수 ────────────────────────────────────
        # 매 3시간 API 세션 헬스 체크
        add(self._job_health_check,
            CronTrigger(hour="*/3", minute=30, timezone=HKT),
            id="futures_health_check")

        # 매일 KST 18:10 일일 평가자산 스냅샷 저장 (통합비교 시계열 누적용)
        add(self._job_save_snapshot,
            CronTrigger(hour=18, minute=10, timezone=KST),
            id="futures_save_snapshot")

        # 매일 08:00 HKT 심볼 갱신 (롤오버 체크)
        add(self._job_refresh_symbols,
            CronTrigger(hour=8, minute=0, timezone=HKT),
            id="futures_refresh_symbols")

    # ── 스케줄 작업 ──────────────────────────────────────

    async def _job_session_open(self):
        """신규 세션 시작"""
        log.info("[선물] 세션 시작")
        try:
            await self.risk.record_starting_equity()

            try:
                await self.realtime.start()
                await self.notify(f"[선물] 세션 시작 - 실시간 모니터링 가동 ({_now_str()})")
            except Exception as e:
                log.error("[선물] 실시간 연결 실패 - 폴링 모드: %s", e)
                await self.notify(f"[선물] 세션 시작 - 실시간 연결 실패, 폴링 모드 ({_now_str()})")
        except Exception as e:
            log.exception("[선물] 세션 시작 실패")
            await self.notify(f"[선물] 세션 시작 실패: {e}")

    async def _job_session_close(self):
        """세션 마감"""
        log.info("[선물] 세션 마감")
        try:
            if self.realtime:
                await self.realtime.stop()
            await self.risk.reset_daily()
            await self.notify(f"[선물] 세션 마감 ({_now_str()})")
        except Exception as e:
            log.exception("[선물] 세션 마감 처리 실패")

    async def _job_check_buy(self):
        """매수 체크"""
        if not self._target_symbols:
            self._target_symbols = await self.engine.prepare_symbols()
        try:
            await self.engine.check_and_buy(self._target_symbols)
        except Exception as e:
            log.exception("[선물] 매수 체크 실패")
            await self.notify(f"[선물] 매수 체크 오류: {e}")

    async def _job_check_stops(self):
        """트레일링 스탑 체크"""
        try:
            async with self._stop_lock:
                await self.engine.check_trailing_stops()
        except Exception as e:
            log.exception("[선물] 트레일링 스탑 체크 실패")
            await self.notify(f"[선물] 스탑 체크 오류: {e}")

    async def _job_check_risk(self):
        """리스크 체크"""
        try:
            await self.risk.check_risk()
        except Exception as e:
            log.exception("[선물] 리스크 체크 실패")

    async def _job_daily_report(self):
        """일일 리포트 생성"""
        try:
            trades = await repo.get_today_futures_trades()
            positions = await repo.get_futures_positions()
            balance = await self.client.get_balance()

            entries = [t for t in trades if t["order_type"] == "ENTRY"]
            exits = [t for t in trades if t["order_type"] == "EXIT"]
            winning = [t for t in exits if (t.get("pnl") or 0) > 0]

            equity = balance.get("eval_asset", 0) if balance else 0
            margin_used = balance.get("margin_used", 0) if balance else 0
            margin_rate = (margin_used / equity * 100) if equity > 0 else 0

            report = {
                "report_date": datetime.now(HKT).strftime("%Y-%m-%d"),
                "starting_equity": self.risk.starting_equity or 0,
                "ending_equity": equity,
                "daily_pnl": equity - (self.risk.starting_equity or 0),
                "daily_pnl_rate": 0,
                "margin_used": margin_used,
                "margin_rate": margin_rate,
                "total_trades": len(trades),
                "winning_trades": len(winning),
                "losing_trades": len(exits) - len(winning),
                "risk_stop_triggered": int(
                    await repo.get_setting("futures_risk_stopped") == "1"),
            }
            if self.risk.starting_equity and self.risk.starting_equity > 0:
                report["daily_pnl_rate"] = (
                    report["daily_pnl"] / self.risk.starting_equity
                ) * 100

            await repo.save_futures_daily_report(report)

            msg = (
                f"<b>[선물] 일일 리포트</b> ({_now_str()})\n\n"
                f"시작 예탁: ${report['starting_equity']:,.2f}\n"
                f"종료 예탁: ${report['ending_equity']:,.2f}\n"
                f"일일 손익: ${report['daily_pnl']:+,.2f} "
                f"({report['daily_pnl_rate']:+.1f}%)\n"
                f"증거금 사용: ${margin_used:,.2f} ({margin_rate:.1f}%)\n"
                f"매매: {report['total_trades']}건 "
                f"(수익 {report['winning_trades']}, 손실 {report['losing_trades']})\n"
                f"보유 포지션: {len(positions)}개\n"
                f"리스크 청산: {'발동' if report['risk_stop_triggered'] else '없음'}"
            )
            await self.notify(msg)
        except Exception as e:
            log.exception("[선물] 일일 리포트 생성 실패")
            await self.notify(f"[선물] 일일 리포트 실패: {e}")

    async def _job_health_check(self):
        """API 세션 헬스 체크"""
        try:
            balance = await self.client.get_balance()
            if not balance:
                log.warning("[선물] 헬스 체크 실패 - 재연결 시도")
                await self.client.reconnect()
                await self.notify(f"[선물] API 세션 재연결 완료 ({_now_str()})")
        except Exception as e:
            log.error("[선물] 헬스 체크 중 재연결 실패: %s", e)
            await self.notify(f"[선물] API 세션 재연결 실패: {e}")

    async def _job_save_snapshot(self):
        """매일 1회 futures_daily_reports에 오늘자 평가자산 저장."""
        try:
            snap = await self.client.get_today_snapshot()
            v = snap.get("eval_asset", 0)
            if v:
                today_kst = datetime.now(KST).strftime("%Y-%m-%d")
                await repo.upsert_futures_daily_equity(today_kst, v)
                log.info("[선물] 일일 스냅샷 저장 %s: $%s", today_kst, f"{v:,.2f}")
        except Exception as e:
            log.warning("[선물] 스냅샷 저장 실패: %s", e)

    async def _job_refresh_symbols(self):
        """거래 대상 심볼 갱신 (롤오버 체크)"""
        try:
            old_symbols = [s["symbol"] for s in self._target_symbols]
            self._target_symbols = await self.engine.prepare_symbols()
            new_symbols = [s["symbol"] for s in self._target_symbols]

            changed = set(new_symbols) - set(old_symbols)
            if changed:
                await self.notify(
                    f"[선물] 심볼 롤오버: {list(changed)} ({_now_str()})")
                log.info("[선물] 심볼 갱신: %s → %s", old_symbols, new_symbols)
        except Exception as e:
            log.exception("[선물] 심볼 갱신 실패")

    # ── 콜백 ─────────────────────────────────────────────

    async def _on_new_buy(self, symbol: str):
        """매수 후 실시간 구독 추가"""
        if self.realtime:
            await self.realtime.subscribe(symbol)

    async def _on_realtime_price(self, symbol: str, price: float):
        """실시간 체결 시 트레일링 스탑 업데이트"""
        async with self._stop_lock:
            pos = await repo.get_futures_position(symbol)
            if not pos:
                return

            settings = await repo.get_all_settings()
            atr_mult = float(settings.get("futures_atr_multiplier",
                                           str(config.FUTURES_ATR_MULTIPLIER)))
            atr = pos["atr"]

            if pos["direction"] == "LONG":
                if price > pos["highest_price"]:
                    new_stop = price - atr * atr_mult
                    await repo.upsert_futures_position(
                        symbol=pos["symbol"],
                        base_symbol=pos["base_symbol"],
                        direction=pos["direction"],
                        quantity=pos["quantity"],
                        avg_entry_price=pos["avg_entry_price"],
                        highest_price=price,
                        lowest_price=pos["lowest_price"],
                        trailing_stop_price=new_stop,
                        atr=atr,
                        tick_size=pos["tick_size"],
                        tick_value=pos["tick_value"],
                        entry_date=pos["entry_date"],
                    )
                elif price <= pos["trailing_stop_price"]:
                    await self.engine._close_position(pos, price, "TRAILING_STOP")
                    if self.realtime:
                        await self.realtime.unsubscribe(symbol)

    async def stop(self):
        """시스템 종료"""
        self.scheduler.shutdown(wait=False)
        if self.realtime:
            await self.realtime.stop()
        await self.notify(f"[선물] 모의투자 봇 종료 ({_now_str()})")
        log.info("[선물] 시스템 종료 완료")
