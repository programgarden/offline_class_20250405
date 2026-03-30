"""메인 스케줄러: 24시간 자동 스케줄링 (미국 동부시간 기준)"""
import asyncio
import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from analyzer.stock_screener import screen_stocks
from database import repository as repo
from risk.risk_manager import RiskManager
from trader.engine import TradingEngine
from trader.ls_client import LSClient
from trader.realtime import RealtimeMonitor
from tgbot.bot import TelegramBot

log = logging.getLogger(__name__)
ET = ZoneInfo("America/New_York")
KST = ZoneInfo("Asia/Seoul")


def _now_str() -> str:
    """한국시간 + 미국동부시간 문자열"""
    kst = datetime.now(KST).strftime("%H:%M")
    et = datetime.now(ET).strftime("%H:%M")
    return f"한국시간 {kst} / 미국동부시간 {et}"


class TurtleScheduler:
    def __init__(self):
        self.client = LSClient()
        self.telegram = TelegramBot()
        self.engine: TradingEngine | None = None
        self.risk: RiskManager | None = None
        self.realtime: RealtimeMonitor | None = None
        self.scheduler = AsyncIOScheduler(timezone=ET)
        self._selected_stocks: list[dict] = []
        self._stop_lock = asyncio.Lock()  # 트레일링 스탑 동시 실행 방지

    async def start(self):
        """시스템 시작"""
        # 로그인 (재시도 포함)
        try:
            await self.client.login()
        except Exception as e:
            log.critical("LS증권 로그인 실패 - 시스템 시작 불가: %s", e)
            raise

        # 텔레그램 시작
        await self.telegram.start()

        # 엔진 초기화
        self.engine = TradingEngine(
            self.client,
            notify_fn=self.telegram.send,
            on_buy_fn=self._on_new_buy,
        )
        self.risk = RiskManager(self.client, self.engine, notify_fn=self.telegram.send)
        self.realtime = RealtimeMonitor(self.client, on_price_update=self._on_realtime_price)

        # DB에서 선정 종목 로드 (이전 분석 결과 복원)
        saved = await repo.get_selected_stocks()
        if saved:
            self._selected_stocks = saved
            log.info("DB에서 선정 종목 %d개 로드", len(saved))

        # 스케줄 등록 (미국 동부시간 기준)
        self._setup_schedule()
        self.scheduler.start()

        msg = f"터틀 트레이딩 봇 시작 ({_now_str()})"
        log.info(msg)
        await self.telegram.send(msg)

    def _setup_schedule(self):
        """스케줄 등록 (미국 동부시간)"""
        add = self.scheduler.add_job

        # ── 일일 관리 ────────────────────────────────────
        # 06:30 ET - 장 마감 정리 + 일일 리포트
        add(self._job_daily_report, CronTrigger(hour=6, minute=30, timezone=ET),
            id="daily_report")

        # 07:00 ET - 리스크 상태 초기화
        add(self._job_reset_risk, CronTrigger(hour=7, minute=0, timezone=ET),
            id="reset_risk")

        # 17:00 ET - 종목 분석 (장 마감 후)
        add(self._job_analyze, CronTrigger(hour=17, minute=0, timezone=ET),
            id="analyze")

        # ── 프리마켓 (04:00~09:00 ET) ────────────────────
        # 매수 체크 (30분 간격)
        add(self._job_check_buy, CronTrigger(hour="4-8", minute="0,30", timezone=ET),
            id="premarket_buy")

        # 트레일링 스탑 체크 (30분 간격) ← 신규 추가
        add(self._job_check_stops, CronTrigger(hour="4-8", minute="0,30", timezone=ET),
            id="premarket_stops")

        # 리스크 체크 (30분 간격) ← 신규 추가
        add(self._job_check_risk, CronTrigger(hour="4-8", minute="0,30", timezone=ET),
            id="premarket_risk")

        # ── 정규장 (09:30~16:00 ET) ──────────────────────
        # 09:30 ET - 정규장 시작: 잔고 기록 + 실시간 연결
        add(self._job_market_open, CronTrigger(hour=9, minute=30, timezone=ET),
            id="market_open")

        # 매수 체크 (15분 간격)
        add(self._job_check_buy, CronTrigger(hour="9-15", minute="*/15", timezone=ET),
            id="regular_buy")

        # 트레일링 스탑 체크 (5분 간격)
        add(self._job_check_stops, CronTrigger(hour="9-15", minute="*/5", timezone=ET),
            id="check_stops")

        # 리스크 체크 (1분 간격)
        add(self._job_check_risk, CronTrigger(hour="9-15", minute="*", timezone=ET),
            id="check_risk")

        # 16:05 ET - 정규장 마감: 실시간 종료
        add(self._job_market_close, CronTrigger(hour=16, minute=5, timezone=ET),
            id="market_close")

        # ── 세션 유지 ────────────────────────────────────
        # 매 3시간마다 API 세션 헬스 체크 ← 신규 추가
        add(self._job_health_check, CronTrigger(hour="*/3", minute=0, timezone=ET),
            id="health_check")

    # ── 스케줄 작업 ──────────────────────────────────────

    async def _job_analyze(self):
        """종목 분석"""
        log.info("종목 분석 시작")
        try:
            self._selected_stocks = await screen_stocks(self.client)
            symbols = [s["symbol"] for s in self._selected_stocks]
            msg = f"종목 분석 완료 ({_now_str()})\n선정: {symbols}"
            await self.telegram.send(msg)
        except Exception as e:
            log.exception("종목 분석 실패")
            await self.telegram.send(f"종목 분석 실패: {e}")

    async def _job_market_open(self):
        """정규장 시작"""
        log.info("정규장 시작")
        try:
            await self.risk.record_starting_balance()

            # 실시간 연결 (실패해도 정규장 진행)
            try:
                await self.realtime.start()
                await self.telegram.send(f"정규장 시작 - 실시간 모니터링 가동 ({_now_str()})")
            except Exception as e:
                log.error("실시간 연결 실패 - 폴링 모드로 운영: %s", e)
                await self.telegram.send(
                    f"⚠ 정규장 시작 - 실시간 연결 실패, 폴링 모드 ({_now_str()})\n{e}"
                )
        except Exception as e:
            log.exception("정규장 시작 실패")
            await self.telegram.send(f"정규장 시작 실패: {e}")

    async def _job_market_close(self):
        """정규장 마감"""
        log.info("정규장 마감")
        try:
            if self.realtime:
                await self.realtime.stop()
            await self.telegram.send(f"정규장 마감 - 실시간 모니터링 종료 ({_now_str()})")
        except Exception as e:
            log.exception("정규장 마감 처리 실패")

    async def _job_check_buy(self):
        """매수 체크"""
        if not self._selected_stocks:
            # DB에서 선정 종목 로드
            selected = await repo.get_selected_stocks()
            if selected:
                self._selected_stocks = selected
        try:
            await self.engine.check_and_buy(self._selected_stocks)
        except Exception as e:
            log.exception("매수 체크 실패")
            await self.telegram.send(f"매수 체크 오류: {e}")

    async def _job_check_stops(self):
        """트레일링 스탑 체크"""
        try:
            async with self._stop_lock:
                await self.engine.check_trailing_stops()
        except Exception as e:
            log.exception("트레일링 스탑 체크 실패")
            await self.telegram.send(f"스탑 체크 오류: {e}")

    async def _job_check_risk(self):
        """리스크 체크"""
        try:
            await self.risk.check_risk()
        except Exception as e:
            log.exception("리스크 체크 실패")

    async def _job_daily_report(self):
        """일일 리포트 생성"""
        try:
            trades = await repo.get_today_trades()
            positions = await repo.get_positions()
            balance = await self.client.get_balance()

            buys = [t for t in trades if t["order_type"] == "BUY"]
            sells = [t for t in trades if t["order_type"] == "SELL"]

            # 승패 판정: 매도가 vs 매수가 비교
            winning = []
            for sell in sells:
                buy_price = await repo.get_last_buy_price(sell["symbol"])
                if buy_price and sell["price"] > buy_price:
                    winning.append(sell)

            report = {
                "report_date": datetime.now(ET).strftime("%Y-%m-%d"),
                "starting_balance": self.risk.starting_balance or 0,
                "ending_balance": balance.get("deposit", 0) if balance else 0,
                "daily_pnl": (balance.get("deposit", 0) - (self.risk.starting_balance or 0))
                             if balance else 0,
                "daily_pnl_rate": 0,
                "total_trades": len(trades),
                "winning_trades": len(winning),
                "losing_trades": len(sells) - len(winning),
                "risk_stop_triggered": int(await repo.get_setting("risk_stopped") == "1"),
            }
            if self.risk.starting_balance and self.risk.starting_balance > 0:
                report["daily_pnl_rate"] = (report["daily_pnl"] / self.risk.starting_balance) * 100

            await repo.save_daily_report(report)

            msg = (
                f"<b>일일 리포트</b> ({_now_str()})\n\n"
                f"시작 잔고: ${report['starting_balance']:,.2f}\n"
                f"종료 잔고: ${report['ending_balance']:,.2f}\n"
                f"일일 손익: ${report['daily_pnl']:+,.2f} ({report['daily_pnl_rate']:+.1f}%)\n"
                f"매매: {report['total_trades']}건 "
                f"(수익 {report['winning_trades']}, 손실 {report['losing_trades']})\n"
                f"보유 종목: {len(positions)}개\n"
                f"리스크 청산: {'발동' if report['risk_stop_triggered'] else '없음'}"
            )
            await self.telegram.send(msg)
        except Exception as e:
            log.exception("일일 리포트 생성 실패")
            await self.telegram.send(f"일일 리포트 실패: {e}")

    async def _job_reset_risk(self):
        """리스크 초기화"""
        try:
            await self.risk.reset_daily()
        except Exception as e:
            log.exception("리스크 초기화 실패")

    async def _job_health_check(self):
        """API 세션 헬스 체크 (예수금 조회로 확인, 실패 시 재연결)"""
        try:
            balance = await self.client.get_balance()
            if not balance:
                log.warning("헬스 체크 실패 - 세션 재연결 시도")
                await self.client.reconnect()
                await self.telegram.send(f"API 세션 재연결 완료 ({_now_str()})")
        except Exception as e:
            log.error("헬스 체크 중 재연결 실패: %s", e)
            await self.telegram.send(f"API 세션 재연결 실패: {e}")

    # ── 신규 매수 콜백 ─────────────────────────────────────

    async def _on_new_buy(self, symbol: str, exchange_code: str):
        """매수 후 실시간 구독 추가"""
        if self.realtime:
            await self.realtime.subscribe(symbol, exchange_code)

    # ── 실시간 콜백 ──────────────────────────────────────

    async def _on_realtime_price(self, symbol: str, price: float):
        """실시간 체결 시 트레일링 스탑 업데이트"""
        async with self._stop_lock:
            pos = await repo.get_position(symbol)
            if not pos:
                return

            settings = await repo.get_all_settings()
            atr_mult = float(settings.get("atr_multiplier", "3.0"))

            if price > pos["highest_price"]:
                new_stop = round(price - pos["atr"] * atr_mult, 2)
                await repo.upsert_position(
                    symbol=pos["symbol"],
                    exchange_code=pos["exchange_code"],
                    quantity=pos["quantity"],
                    avg_buy_price=pos["avg_buy_price"],
                    highest_price=price,
                    trailing_stop_price=new_stop,
                    atr=pos["atr"],
                    entry_date=pos["entry_date"],
                )
            elif price <= pos["trailing_stop_price"]:
                mode = await repo.get_setting("mode") or "dry"
                await self.engine._sell_position(pos, price, "TRAILING_STOP", mode)
                if self.realtime:
                    await self.realtime.unsubscribe(symbol, pos["exchange_code"])

    async def stop(self):
        """시스템 종료"""
        self.scheduler.shutdown(wait=False)
        if self.realtime:
            await self.realtime.stop()
        await self.telegram.send(f"터틀 트레이딩 봇 종료 ({_now_str()})")
        await self.telegram.stop()
        log.info("시스템 종료 완료")
