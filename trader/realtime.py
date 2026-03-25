"""실시간 모니터링: WebSocket GSC 체결 데이터 + 트레일링 스탑 연동"""
import logging

from database import repository as repo
from trader.ls_client import LSClient

log = logging.getLogger(__name__)


class RealtimeMonitor:
    def __init__(self, client: LSClient, on_price_update=None):
        self.client = client
        self.on_price_update = on_price_update
        self._real = None

    async def start(self):
        """실시간 연결 시작 + 보유 종목 구독"""
        self._real = self.client.stock.real(reconnect=True)
        await self._real.connect(wait=True, timeout=10.0)
        log.info("실시간 WebSocket 연결됨")

        positions = await repo.get_positions()
        if positions:
            symbols = [f"{p['exchange_code']}{p['symbol']}" for p in positions]
            gsc = self._real.GSC()
            gsc.add_gsc_symbols(symbols)
            gsc.on_gsc_message(self._on_tick)
            log.info("실시간 구독: %s", symbols)

    async def _on_tick(self, msg):
        """실시간 체결 콜백"""
        body = msg.body
        symbol = body.symbol
        price = float(body.price)

        if self.on_price_update:
            await self.on_price_update(symbol, price)

    async def subscribe(self, symbol: str, exchange_code: str):
        """종목 추가 구독"""
        if self._real:
            keysymbol = f"{exchange_code}{symbol}"
            self._real.GSC().add_gsc_symbols([keysymbol])
            log.info("실시간 구독 추가: %s", keysymbol)

    async def unsubscribe(self, symbol: str, exchange_code: str):
        """종목 구독 해제"""
        if self._real:
            keysymbol = f"{exchange_code}{symbol}"
            self._real.GSC().remove_gsc_symbols([keysymbol])

    async def stop(self):
        """실시간 연결 종료"""
        if self._real:
            await self._real.close()
            log.info("실시간 WebSocket 연결 종료")
