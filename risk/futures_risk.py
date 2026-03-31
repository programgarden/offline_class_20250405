"""선물 리스크 관리자: 증거금 기반 일일 손실률 감시 + 3%/5% 한도 청산"""
import logging

import config
from database import repository as repo
from trader.futures_engine import FuturesEngine
from trader.futures_client import FuturesClient

log = logging.getLogger(__name__)


class FuturesRiskManager:
    def __init__(self, client: FuturesClient, engine: FuturesEngine, notify_fn=None):
        self.client = client
        self.engine = engine
        self.notify = notify_fn or (lambda msg: None)
        self.starting_equity: float | None = None

    async def record_starting_equity(self):
        """장 시작 시 기준 예탁자산 기록"""
        balance = await self.client.get_balance()
        if balance:
            self.starting_equity = balance.get("eval_asset", 0) or balance.get("deposit", 0)
            log.info("[선물] 장 시작 예탁자산: $%.2f", self.starting_equity)

    async def check_risk(self):
        """현재 손실률 체크 → 3%/5% 초과 시 청산 실행"""
        if self.starting_equity is None or self.starting_equity <= 0:
            return

        if await repo.get_setting("futures_risk_stopped") == "1":
            return

        balance = await self.client.get_balance()
        if not balance:
            return

        current_equity = balance.get("eval_asset", 0) or balance.get("deposit", 0)
        loss_pct = ((self.starting_equity - current_equity) / self.starting_equity) * 100

        if loss_pct >= config.FUTURES_RISK_STOP_PCT:
            msg = (
                f"[선물] 5% 비상 청산! 손실률: {loss_pct:.1f}%\n"
                f"전 포지션 매도 + 당일 매매 중단"
            )
            log.critical(msg)
            await self.notify(msg)
            await self.engine.close_all_positions()
            await repo.set_setting("futures_risk_stopped", "1")
            await repo.set_setting("futures_trading_paused", "1")

        elif loss_pct >= config.FUTURES_RISK_WARN_PCT:
            msg = (
                f"[선물] 3% 손실 경고! 손실률: {loss_pct:.1f}%\n"
                f"마이너스 포지션 청산"
            )
            log.warning(msg)
            await self.notify(msg)
            await self.engine.close_losing_positions()

    async def check_margin_rate(self) -> float:
        """증거금 사용률 반환 (%)"""
        balance = await self.client.get_balance()
        if not balance:
            return 0.0

        equity = balance.get("eval_asset", 0) or balance.get("deposit", 0)
        margin_used = balance.get("margin_used", 0)
        if equity <= 0:
            return 0.0
        return (margin_used / equity) * 100

    async def reset_daily(self):
        """일일 리스크 상태 초기화"""
        await repo.set_setting("futures_risk_stopped", "0")
        self.starting_equity = None
        log.info("[선물] 일일 리스크 상태 초기화")
