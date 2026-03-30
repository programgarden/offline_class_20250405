"""텔레그램 봇: 알림 전송 + 명령어 수신"""
import logging
from telegram import Update, Bot
from telegram.ext import Application, CommandHandler, ContextTypes

import config
from database import repository as repo

log = logging.getLogger(__name__)


class TelegramBot:
    def __init__(self):
        self.app: Application | None = None
        self.bot: Bot | None = None
        self._chat_id = config.TELEGRAM_CHAT_ID

    async def start(self):
        """텔레그램 봇 시작"""
        if not config.TELEGRAM_BOT_TOKEN:
            log.warning("텔레그램 토큰 미설정 - 봇 비활성화")
            return

        self.app = Application.builder().token(config.TELEGRAM_BOT_TOKEN).build()
        self.bot = self.app.bot

        # 명령어 핸들러 등록
        handlers = {
            "help": self._cmd_help,
            "status": self._cmd_status,
            "mode": self._cmd_mode,
            "set": self._cmd_set,
            "settings": self._cmd_settings,
            "stop": self._cmd_stop,
            "start": self._cmd_start,
            "report": self._cmd_report,
        }
        for cmd, handler in handlers.items():
            self.app.add_handler(CommandHandler(cmd, handler))

        await self.app.initialize()
        await self.app.start()
        await self.app.updater.start_polling(
            drop_pending_updates=True,
            poll_interval=300,  # 5분 간격 폴링
        )
        log.info("텔레그램 봇 시작됨")

    async def stop(self):
        if self.app:
            await self.app.updater.stop()
            await self.app.stop()
            await self.app.shutdown()

    async def send(self, message: str):
        """메시지 전송"""
        if self.bot and self._chat_id:
            try:
                await self.bot.send_message(
                    chat_id=self._chat_id,
                    text=message,
                    parse_mode="HTML",
                )
            except Exception as e:
                log.error("텔레그램 전송 실패: %s", e)

    # ── 인증 ───────────────────────────────────────────

    def _is_authorized(self, update: Update) -> bool:
        """허가된 chat_id인지 확인"""
        return str(update.effective_chat.id) == str(self._chat_id)

    # ── 명령어 핸들러 ────────────────────────────────────

    async def _cmd_help(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        if not self._is_authorized(update):
            return
        text = (
            "<b>터틀 트레이딩 봇 명령어</b>\n\n"
            "/help - 명령어 목록\n"
            "/status - 현재 상태 (보유종목, 손익)\n"
            "/mode - 현재 모드 확인\n"
            "/mode live - 실전 모드 전환\n"
            "/mode dry - 드라이런 모드 전환\n"
            "/set channel 20 - 돈치안 채널 기간\n"
            "/set atr 3.0 - ATR 배수\n"
            "/set stocks 5 - 종목 수\n"
            "/set ratio 50 - 예수금 사용 비율(%)\n"
            "/settings - 전체 설정값 보기\n"
            "/stop - 매매 일시 중단\n"
            "/start - 매매 재개\n"
            "/report - 최근 매매 리포트"
        )
        await update.message.reply_text(text, parse_mode="HTML")

    async def _cmd_status(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        if not self._is_authorized(update):
            return
        positions = await repo.get_positions()
        mode = await repo.get_setting("mode") or config.DEFAULT_MODE
        paused = await repo.get_setting("trading_paused") == "1"

        lines = [
            f"<b>모드:</b> {mode}",
            f"<b>매매:</b> {'중단' if paused else '활성'}",
            f"<b>보유 종목:</b> {len(positions)}개\n",
        ]
        for p in positions:
            pnl_pct = ((float(p['highest_price']) - p['avg_buy_price']) / p['avg_buy_price']) * 100
            lines.append(
                f"  {p['symbol']} {p['quantity']}주 @ ${p['avg_buy_price']:.2f} "
                f"(스탑 ${p['trailing_stop_price']:.2f})"
            )
        await update.message.reply_text("\n".join(lines), parse_mode="HTML")

    async def _cmd_mode(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        if not self._is_authorized(update):
            return
        args = ctx.args
        if not args:
            mode = await repo.get_setting("mode") or config.DEFAULT_MODE
            await update.message.reply_text(f"현재 모드: <b>{mode}</b>", parse_mode="HTML")
            return

        new_mode = args[0].lower()
        if new_mode not in (config.MODE_DRY, config.MODE_LIVE):
            await update.message.reply_text("사용법: /mode dry 또는 /mode live")
            return

        await repo.set_setting("mode", new_mode)
        await update.message.reply_text(f"모드 변경: <b>{new_mode}</b>", parse_mode="HTML")

    async def _cmd_set(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        if not self._is_authorized(update):
            return
        if len(ctx.args) < 2:
            await update.message.reply_text(
                "사용법: /set [channel|atr|stocks|ratio] [값]"
            )
            return

        param, value = ctx.args[0].lower(), ctx.args[1]
        key_map = {
            "channel": "donchian_period",
            "atr": "atr_multiplier",
            "stocks": "max_stocks",
            "ratio": "capital_ratio",
        }
        if param not in key_map:
            await update.message.reply_text(f"알 수 없는 파라미터: {param}")
            return

        try:
            float(value)
        except ValueError:
            await update.message.reply_text(f"잘못된 값: {value}")
            return

        await repo.set_setting(key_map[param], value)
        await update.message.reply_text(f"설정 변경: <b>{param} = {value}</b>", parse_mode="HTML")

    async def _cmd_settings(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        if not self._is_authorized(update):
            return
        settings = await repo.get_all_settings()
        lines = ["<b>현재 설정값</b>\n"]
        for k, v in settings.items():
            lines.append(f"  {k}: {v}")
        await update.message.reply_text("\n".join(lines), parse_mode="HTML")

    async def _cmd_stop(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        if not self._is_authorized(update):
            return
        await repo.set_setting("trading_paused", "1")
        await update.message.reply_text("매매 일시 중단됨")

    async def _cmd_start(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        if not self._is_authorized(update):
            return
        await repo.set_setting("trading_paused", "0")
        await update.message.reply_text("매매 재개됨")

    async def _cmd_report(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        if not self._is_authorized(update):
            return
        trades = await repo.get_today_trades()
        if not trades:
            await update.message.reply_text("오늘 매매 내역 없음")
            return

        buys = [t for t in trades if t["order_type"] == "BUY"]
        sells = [t for t in trades if t["order_type"] == "SELL"]
        total_buy = sum(t["amount"] for t in buys)
        total_sell = sum(t["amount"] for t in sells)

        lines = [
            f"<b>오늘 매매 리포트</b>\n",
            f"매수: {len(buys)}건 (${total_buy:,.2f})",
            f"매도: {len(sells)}건 (${total_sell:,.2f})\n",
        ]
        for t in trades[:10]:
            dry = "[DRY] " if t.get("is_dry_run") else ""
            lines.append(
                f"  {dry}{t['order_type']} {t['symbol']} "
                f"{t['quantity']}주 @ ${t['price']:.2f} ({t['reason']})"
            )
        await update.message.reply_text("\n".join(lines), parse_mode="HTML")
