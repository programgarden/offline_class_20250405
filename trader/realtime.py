"""실시간 모니터링: WebSocket GSC 체결 데이터 + 트레일링 스탑 연동"""
import asyncio
import logging

import config
from database import repository as repo
from trader.ls_client import LSClient

log = logging.getLogger(__name__)


class RealtimeMonitor:
    def __init__(self, client: LSClient, on_price_update=None):
        self.client = client
        self.on_price_update = on_price_update
        self._real = None
        self._running = False

    async def start(self):
        """실시간 연결 시작 + 보유 종목 구독 (재시도 포함)"""
        max_retries = config.WS_MAX_RETRIES
        base_delay = config.WS_RETRY_BASE_DELAY

        for attempt in range(1, max_retries + 1):
            try:
                self._real = self.client.stock.real(reconnect=True)
                await self._real.connect(wait=True, timeout=10.0)
                self._running = True
                log.info("실시간 WebSocket 연결됨")

                positions = await repo.get_positions()
                if positions:
                    symbols = [f"{p['exchange_code']}{p['symbol']}" for p in positions]
                    gsc = self._real.GSC()
                    gsc.add_gsc_symbols(symbols)
                    gsc.on_gsc_message(self._on_tick)
                    log.info("실시간 구독: %s", symbols)
                return

            except Exception as e:
                if attempt == max_retries:
                    log.error("실시간 WebSocket 연결 최종 실패 (%d회 시도): %s", max_retries, e)
                    raise
                delay = base_delay * attempt
                log.warning("WebSocket 연결 재시도 %d/%d (%d초 후): %s",
                            attempt, max_retries, delay, e)
                await asyncio.sleep(delay)

    async def restart(self):
        """실시간 연결 재시작 (끊김 복구용)"""
        log.info("실시간 WebSocket 재시작 시도")
        try:
            await self.stop()
        except Exception:
            pass
        await self.start()

    async def _on_tick(self, msg):
        """실시간 체결 콜백"""
        body = msg.body
        symbol = body.symbol
        price = float(body.price)

        if self.on_price_update:
            try:
                await self.on_price_update(symbol, price)
            except Exception as e:
                log.error("실시간 가격 콜백 처리 실패 %s: %s", symbol, e)

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
        self._running = False
        if self._real:
            try:
                await self._real.close()
            except Exception as e:
                log.warning("WebSocket 종료 중 오류 (무시): %s", e)
            self._real = None
            log.info("실시간 WebSocket 연결 종료")
