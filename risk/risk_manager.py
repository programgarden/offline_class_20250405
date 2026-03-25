"""리스크 관리자: 일일 손실률 감시 + 4%/5% 한도 청산"""
import logging

import config
from database import repository as repo
from trader.engine import TradingEngine
from trader.ls_client import LSClient

log = logging.getLogger(__name__)


class RiskManager:
    def __init__(self, client: LSClient, engine: TradingEngine, notify_fn=None):
        self.client = client
        self.engine = engine
        self.notify = notify_fn or (lambda msg: None)
        self.starting_balance: float | None = None

    async def record_starting_balance(self):
        """장 시작 시 기준 잔고 기록"""
        balance = await self.client.get_balance()
        if balance:
            self.starting_balance = balance["deposit"]
            log.info("장 시작 잔고: $%.2f", self.starting_balance)

    async def check_risk(self):
        """현재 손실률 체크 → 4%/5% 초과 시 청산 실행"""
        if self.starting_balance is None or self.starting_balance <= 0:
            return

        # 이미 리스크 청산 상태면 스킵
        if await repo.get_setting("risk_stopped") == "1":
            return

        balance = await self.client.get_balance()
        if not balance:
            return

        current = balance["deposit"]
        # 보유종목 평가금액도 포함
        holdings = await self.client.get_holdings()
        eval_total = current + sum(h["eval_amount"] for h in holdings)

        loss_pct = ((self.starting_balance - eval_total) / self.starting_balance) * 100

        if loss_pct >= config.RISK_STOP_PCT:
            msg = f"5% 비상 청산! 손실률: {loss_pct:.1f}%\n전종목 매도 + 당일 매매 중단"
            log.critical(msg)
            await self.notify(msg)
            await self.engine.sell_all_positions()
            await repo.set_setting("risk_stopped", "1")
            await repo.set_setting("trading_paused", "1")

        elif loss_pct >= config.RISK_WARN_PCT:
            msg = f"4% 손실 경고! 손실률: {loss_pct:.1f}%\n마이너스 종목 청산"
            log.warning(msg)
            await self.notify(msg)
            await self.engine.sell_losing_positions()

    async def reset_daily(self):
        """일일 리스크 상태 초기화 (다음 거래일 시작 시)"""
        await repo.set_setting("risk_stopped", "0")
        self.starting_balance = None
        log.info("일일 리스크 상태 초기화")
