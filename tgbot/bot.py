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
            # 선물 명령어
            "fstatus": self._cmd_fstatus,
            "fset": self._cmd_fset,
            "fsettings": self._cmd_fsettings,
            "fstop": self._cmd_fstop,
            "fstart": self._cmd_fstart,
            "freport": self._cmd_freport,
            "flist": self._cmd_flist,
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
            "<b>[ 해외주식 ]</b>\n"
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
            "/report - 최근 매매 리포트\n\n"
            "<b>[ 해외선물 (모의투자) ]</b>\n"
            "/fstatus - 선물 포지션, 증거금, 손익\n"
            "/fset channel 20 - 선물 돈치안 기간\n"
            "/fset atr 3.0 - 선물 ATR 배수\n"
            "/fset contracts 5 - 최대 종목 수\n"
            "/fset risk 2.0 - 1종목 리스크(%)\n"
            "/fsettings - 선물 설정값 보기\n"
            "/fstop - 선물 매매 중단\n"
            "/fstart - 선물 매매 재개\n"
            "/freport - 선물 매매 리포트\n"
            "/flist - 거래 대상 선물 목록"
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

    # ── 선물 명령어 핸들러 ───────────────────────────────

    async def _cmd_fstatus(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        if not self._is_authorized(update):
            return
        positions = await repo.get_futures_positions()
        paused = await repo.get_setting("futures_trading_paused") == "1"

        lines = [
            f"<b>[선물] 모의투자</b>",
            f"<b>매매:</b> {'중단' if paused else '활성'}",
            f"<b>보유 포지션:</b> {len(positions)}개\n",
        ]
        for p in positions:
            lines.append(
                f"  {p['symbol']} ({p['direction']}) "
                f"{p['quantity']}계약 @ {p['avg_entry_price']}\n"
                f"    스탑: {p['trailing_stop_price']:.2f}"
            )
        await update.message.reply_text("\n".join(lines), parse_mode="HTML")

    async def _cmd_fset(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        if not self._is_authorized(update):
            return
        if len(ctx.args) < 2:
            await update.message.reply_text(
                "사용법: /fset [channel|atr|contracts|risk] [값]"
            )
            return

        param, value = ctx.args[0].lower(), ctx.args[1]
        key_map = {
            "channel": "futures_donchian_period",
            "atr": "futures_atr_multiplier",
            "contracts": "futures_max_contracts",
            "risk": "futures_risk_per_trade",
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
        await update.message.reply_text(
            f"[선물] 설정 변경: <b>{param} = {value}</b>", parse_mode="HTML")

    async def _cmd_fsettings(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        if not self._is_authorized(update):
            return
        settings = await repo.get_all_settings()
        lines = ["<b>[선물] 설정값</b>\n"]
        for k, v in settings.items():
            if k.startswith("futures_"):
                lines.append(f"  {k}: {v}")
        await update.message.reply_text("\n".join(lines), parse_mode="HTML")

    async def _cmd_fstop(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        if not self._is_authorized(update):
            return
        await repo.set_setting("futures_trading_paused", "1")
        await update.message.reply_text("[선물] 매매 일시 중단됨")

    async def _cmd_fstart(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        if not self._is_authorized(update):
            return
        await repo.set_setting("futures_trading_paused", "0")
        await update.message.reply_text("[선물] 매매 재개됨")

    async def _cmd_freport(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        if not self._is_authorized(update):
            return
        trades = await repo.get_today_futures_trades()
        if not trades:
            await update.message.reply_text("[선물] 오늘 매매 내역 없음")
            return

        entries = [t for t in trades if t["order_type"] == "ENTRY"]
        exits = [t for t in trades if t["order_type"] == "EXIT"]
        total_pnl = sum(t.get("pnl") or 0 for t in exits)

        lines = [
            f"<b>[선물] 오늘 매매 리포트</b>\n",
            f"진입: {len(entries)}건",
            f"청산: {len(exits)}건",
            f"실현 손익: ${total_pnl:+,.2f}\n",
        ]
        for t in trades[:10]:
            pnl_str = f" P&L ${t['pnl']:+,.2f}" if t.get("pnl") else ""
            lines.append(
                f"  {t['order_type']} {t['symbol']} ({t['direction']}) "
                f"{t['quantity']}계약 @ {t['price']}{pnl_str} ({t['reason']})"
            )
        await update.message.reply_text("\n".join(lines), parse_mode="HTML")

    async def _cmd_flist(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        if not self._is_authorized(update):
            return
        lines = ["<b>[선물] 거래 대상 (홍콩거래소)</b>\n"]
        for item in config.FUTURES_SYMBOLS:
            spec = await repo.get_futures_spec(item["base"])
            tick_info = ""
            if spec:
                tick_info = f" (틱 ${spec['tick_value']}, 증거금 ${spec.get('margin_required', 0):,.0f})"
            lines.append(f"  {item['base']} - {item['name']}{tick_info}")
        await update.message.reply_text("\n".join(lines), parse_mode="HTML")
