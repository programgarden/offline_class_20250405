"""메인 스케줄러: 24시간 자동 스케줄링 (미국 동부시간 기준)"""
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


class TurtleScheduler:
    def __init__(self):
        self.client = LSClient()
        self.telegram = TelegramBot()
        self.engine: TradingEngine | None = None
        self.risk: RiskManager | None = None
        self.realtime: RealtimeMonitor | None = None
        self.scheduler = AsyncIOScheduler(timezone=ET)
        self._selected_stocks: list[dict] = []

    async def start(self):
        """시스템 시작"""
        # 로그인
        await self.client.login()

        # 텔레그램 시작
        await self.telegram.start()

        # 엔진 초기화
        self.engine = TradingEngine(self.client, notify_fn=self.telegram.send)
        self.risk = RiskManager(self.client, self.engine, notify_fn=self.telegram.send)
        self.realtime = RealtimeMonitor(self.client, on_price_update=self._on_realtime_price)

        # 스케줄 등록 (미국 동부시간 기준)
        self._setup_schedule()
        self.scheduler.start()

        now_et = datetime.now(ET).strftime("%H:%M %Z")
        msg = f"터틀 트레이딩 봇 시작 (현재 ET: {now_et})"
        log.info(msg)
        await self.telegram.send(msg)

    def _setup_schedule(self):
        """스케줄 등록 (미국 동부시간)"""
        add = self.scheduler.add_job

        # 06:30 ET - 장 마감 정리 + 일일 리포트
        add(self._job_daily_report, CronTrigger(hour=6, minute=30, timezone=ET),
            id="daily_report")

        # 07:00 ET - 리스크 상태 초기화
        add(self._job_reset_risk, CronTrigger(hour=7, minute=0, timezone=ET),
            id="reset_risk")

        # 17:00 ET - 종목 분석 (장 마감 후)
        add(self._job_analyze, CronTrigger(hour=17, minute=0, timezone=ET),
            id="analyze")

        # 04:00~08:00 ET - 주간거래(프리마켓 포함) 매수 체크 (30분 간격)
        add(self._job_check_buy, CronTrigger(hour="4-8", minute="0,30", timezone=ET),
            id="premarket_buy")

        # 09:30 ET - 정규장 시작: 잔고 기록 + 실시간 연결
        add(self._job_market_open, CronTrigger(hour=9, minute=30, timezone=ET),
            id="market_open")

        # 09:30~16:00 ET - 정규장 매수 체크 (15분 간격)
        add(self._job_check_buy, CronTrigger(hour="9-15", minute="*/15", timezone=ET),
            id="regular_buy")

        # 09:30~16:00 ET - 트레일링 스탑 체크 (5분 간격)
        add(self._job_check_stops, CronTrigger(hour="9-15", minute="*/5", timezone=ET),
            id="check_stops")

        # 09:30~16:00 ET - 리스크 체크 (1분 간격)
        add(self._job_check_risk, CronTrigger(hour="9-15", minute="*", timezone=ET),
            id="check_risk")

        # 16:00 ET - 정규장 마감: 실시간 종료
        add(self._job_market_close, CronTrigger(hour=16, minute=5, timezone=ET),
            id="market_close")

    # ── 스케줄 작업 ──────────────────────────────────────

    async def _job_analyze(self):
        """종목 분석"""
        log.info("종목 분석 시작")
        try:
            self._selected_stocks = await screen_stocks(self.client)
            symbols = [s["symbol"] for s in self._selected_stocks]
            msg = f"종목 분석 완료: {symbols}"
            await self.telegram.send(msg)
        except Exception as e:
            log.exception("종목 분석 실패")
            await self.telegram.send(f"종목 분석 실패: {e}")

    async def _job_market_open(self):
        """정규장 시작"""
        log.info("정규장 시작")
        try:
            await self.risk.record_starting_balance()
            await self.realtime.start()
            await self.telegram.send("정규장 시작 - 실시간 모니터링 가동")
        except Exception as e:
            log.exception("정규장 시작 실패")
            await self.telegram.send(f"정규장 시작 실패: {e}")

    async def _job_market_close(self):
        """정규장 마감"""
        log.info("정규장 마감")
        try:
            if self.realtime:
                await self.realtime.stop()
            await self.telegram.send("정규장 마감 - 실시간 모니터링 종료")
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

    async def _job_check_stops(self):
        """트레일링 스탑 체크"""
        try:
            await self.engine.check_trailing_stops()
        except Exception as e:
            log.exception("트레일링 스탑 체크 실패")

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
            winning = [t for t in sells if t["reason"] == "TRAILING_STOP"
                       and t["price"] > 0]  # 수익 거래 (간이 판단)

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
                f"<b>일일 리포트</b>\n\n"
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

    # ── 실시간 콜백 ──────────────────────────────────────

    async def _on_realtime_price(self, symbol: str, price: float):
        """실시간 체결 시 트레일링 스탑 업데이트"""
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
        await self.telegram.send("터틀 트레이딩 봇 종료")
        await self.telegram.stop()
        log.info("시스템 종료 완료")
