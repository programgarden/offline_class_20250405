import aiosqlite
import config
from datetime import datetime


async def _connect():
    return aiosqlite.connect(config.DB_PATH)


# ── Settings ──────────────────────────────────────────────

async def get_setting(key: str) -> str | None:
    async with await _connect() as db:
        cur = await db.execute("SELECT value FROM settings WHERE key = ?", (key,))
        row = await cur.fetchone()
        return row[0] if row else None


async def set_setting(key: str, value: str):
    async with await _connect() as db:
        await db.execute(
            """INSERT INTO settings (key, value, updated_at)
               VALUES (?, ?, datetime('now'))
               ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at""",
            (key, value),
        )
        await db.commit()


async def get_all_settings() -> dict[str, str]:
    async with await _connect() as db:
        cur = await db.execute("SELECT key, value FROM settings")
        rows = await cur.fetchall()
        return {r[0]: r[1] for r in rows}


# ── Stock Analysis ────────────────────────────────────────

async def save_analysis(rows: list[dict]):
    """분석 결과 일괄 저장. rows = [{symbol, exchange_code, company_name, momentum_score, financial_score, total_score, selected}]"""
    today = datetime.utcnow().strftime("%Y-%m-%d")
    async with await _connect() as db:
        await db.execute("DELETE FROM stock_analysis WHERE analysis_date = ?", (today,))
        for r in rows:
            await db.execute(
                """INSERT INTO stock_analysis
                   (analysis_date, symbol, exchange_code, company_name,
                    momentum_score, financial_score, total_score, selected)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (today, r["symbol"], r["exchange_code"], r.get("company_name", ""),
                 r.get("momentum_score", 0), r.get("financial_score", 0),
                 r.get("total_score", 0), r.get("selected", 0)),
            )
        await db.commit()


async def get_selected_stocks(date: str | None = None) -> list[dict]:
    date = date or datetime.utcnow().strftime("%Y-%m-%d")
    async with await _connect() as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT * FROM stock_analysis WHERE analysis_date = ? AND selected = 1 ORDER BY total_score DESC",
            (date,),
        )
        return [dict(r) for r in await cur.fetchall()]


# ── Positions ─────────────────────────────────────────────

async def upsert_position(symbol: str, exchange_code: str, quantity: int,
                          avg_buy_price: float, highest_price: float,
                          trailing_stop_price: float, atr: float, entry_date: str):
    async with await _connect() as db:
        await db.execute(
            """INSERT INTO positions
               (symbol, exchange_code, quantity, avg_buy_price, highest_price,
                trailing_stop_price, atr, entry_date, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
               ON CONFLICT(symbol) DO UPDATE SET
                 quantity = excluded.quantity,
                 avg_buy_price = excluded.avg_buy_price,
                 highest_price = excluded.highest_price,
                 trailing_stop_price = excluded.trailing_stop_price,
                 atr = excluded.atr,
                 updated_at = datetime('now')""",
            (symbol, exchange_code, quantity, avg_buy_price, highest_price,
             trailing_stop_price, atr, entry_date),
        )
        await db.commit()


async def get_positions() -> list[dict]:
    async with await _connect() as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT * FROM positions")
        return [dict(r) for r in await cur.fetchall()]


async def get_position(symbol: str) -> dict | None:
    async with await _connect() as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT * FROM positions WHERE symbol = ?", (symbol,))
        row = await cur.fetchone()
        return dict(row) if row else None


async def delete_position(symbol: str):
    async with await _connect() as db:
        await db.execute("DELETE FROM positions WHERE symbol = ?", (symbol,))
        await db.commit()


# ── Trades ────────────────────────────────────────────────

async def save_trade(symbol: str, exchange_code: str, order_type: str,
                     order_no: str, quantity: int, price: float,
                     reason: str, is_dry_run: bool = False):
    async with await _connect() as db:
        await db.execute(
            """INSERT INTO trades
               (symbol, exchange_code, order_type, order_no, quantity, price,
                amount, reason, is_dry_run)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (symbol, exchange_code, order_type, order_no, quantity, price,
             quantity * price, reason, int(is_dry_run)),
        )
        await db.commit()


async def get_today_trades() -> list[dict]:
    today = datetime.utcnow().strftime("%Y-%m-%d")
    async with await _connect() as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT * FROM trades WHERE executed_at >= ? ORDER BY executed_at DESC",
            (today,),
        )
        return [dict(r) for r in await cur.fetchall()]


async def get_last_buy_price(symbol: str) -> float | None:
    """종목의 가장 최근 매수 가격 조회"""
    async with await _connect() as db:
        cur = await db.execute(
            "SELECT price FROM trades WHERE symbol = ? AND order_type = 'BUY' "
            "ORDER BY executed_at DESC LIMIT 1",
            (symbol,),
        )
        row = await cur.fetchone()
        return row[0] if row else None


# ── Daily Reports ─────────────────────────────────────────

async def save_daily_report(report: dict):
    async with await _connect() as db:
        await db.execute(
            """INSERT OR REPLACE INTO daily_reports
               (report_date, starting_balance, ending_balance, daily_pnl,
                daily_pnl_rate, total_trades, winning_trades, losing_trades,
                risk_stop_triggered)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (report["report_date"], report.get("starting_balance", 0),
             report.get("ending_balance", 0), report.get("daily_pnl", 0),
             report.get("daily_pnl_rate", 0), report.get("total_trades", 0),
             report.get("winning_trades", 0), report.get("losing_trades", 0),
             report.get("risk_stop_triggered", 0)),
        )
        await db.commit()


# ══ 선물 (Futures) ═══════════════════════════════════════

# ── Futures Specs ────────────────────────────────────────

async def upsert_futures_spec(base_symbol: str, name: str, exchange: str,
                               tick_size: float, tick_value: float,
                               margin_required: float = 0):
    async with await _connect() as db:
        await db.execute(
            """INSERT INTO futures_specs
               (base_symbol, name, exchange, tick_size, tick_value, margin_required, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, datetime('now'))
               ON CONFLICT(base_symbol) DO UPDATE SET
                 tick_size = excluded.tick_size,
                 tick_value = excluded.tick_value,
                 margin_required = excluded.margin_required,
                 updated_at = datetime('now')""",
            (base_symbol, name, exchange, tick_size, tick_value, margin_required),
        )
        await db.commit()


async def get_futures_spec(base_symbol: str) -> dict | None:
    async with await _connect() as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT * FROM futures_specs WHERE base_symbol = ?", (base_symbol,))
        row = await cur.fetchone()
        return dict(row) if row else None


async def get_all_futures_specs() -> list[dict]:
    async with await _connect() as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT * FROM futures_specs")
        return [dict(r) for r in await cur.fetchall()]


# ── Futures Positions ────────────────────────────────────

async def upsert_futures_position(symbol: str, base_symbol: str, direction: str,
                                   quantity: int, avg_entry_price: float,
                                   highest_price: float, lowest_price: float,
                                   trailing_stop_price: float, atr: float,
                                   tick_size: float, tick_value: float,
                                   entry_date: str):
    async with await _connect() as db:
        await db.execute(
            """INSERT INTO futures_positions
               (symbol, base_symbol, direction, quantity, avg_entry_price,
                highest_price, lowest_price, trailing_stop_price, atr,
                tick_size, tick_value, entry_date, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
               ON CONFLICT(symbol) DO UPDATE SET
                 quantity = excluded.quantity,
                 avg_entry_price = excluded.avg_entry_price,
                 highest_price = excluded.highest_price,
                 lowest_price = excluded.lowest_price,
                 trailing_stop_price = excluded.trailing_stop_price,
                 atr = excluded.atr,
                 updated_at = datetime('now')""",
            (symbol, base_symbol, direction, quantity, avg_entry_price,
             highest_price, lowest_price, trailing_stop_price, atr,
             tick_size, tick_value, entry_date),
        )
        await db.commit()


async def get_futures_positions() -> list[dict]:
    async with await _connect() as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT * FROM futures_positions")
        return [dict(r) for r in await cur.fetchall()]


async def get_futures_position(symbol: str) -> dict | None:
    async with await _connect() as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT * FROM futures_positions WHERE symbol = ?", (symbol,))
        row = await cur.fetchone()
        return dict(row) if row else None


async def delete_futures_position(symbol: str):
    async with await _connect() as db:
        await db.execute("DELETE FROM futures_positions WHERE symbol = ?", (symbol,))
        await db.commit()


# ── Futures Trades ───────────────────────────────────────

async def save_futures_trade(symbol: str, base_symbol: str, direction: str,
                              order_type: str, order_no: str, quantity: int,
                              price: float, pnl: float | None, reason: str):
    async with await _connect() as db:
        await db.execute(
            """INSERT INTO futures_trades
               (symbol, base_symbol, direction, order_type, order_no,
                quantity, price, pnl, reason)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (symbol, base_symbol, direction, order_type, order_no,
             quantity, price, pnl, reason),
        )
        await db.commit()


async def get_today_futures_trades() -> list[dict]:
    today = datetime.utcnow().strftime("%Y-%m-%d")
    async with await _connect() as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT * FROM futures_trades WHERE executed_at >= ? ORDER BY executed_at DESC",
            (today,),
        )
        return [dict(r) for r in await cur.fetchall()]


# ── Futures Daily Reports ────────────────────────────────

async def save_futures_daily_report(report: dict):
    async with await _connect() as db:
        await db.execute(
            """INSERT OR REPLACE INTO futures_daily_reports
               (report_date, starting_equity, ending_equity, daily_pnl,
                daily_pnl_rate, margin_used, margin_rate,
                total_trades, winning_trades, losing_trades, risk_stop_triggered)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (report["report_date"], report.get("starting_equity", 0),
             report.get("ending_equity", 0), report.get("daily_pnl", 0),
             report.get("daily_pnl_rate", 0), report.get("margin_used", 0),
             report.get("margin_rate", 0), report.get("total_trades", 0),
             report.get("winning_trades", 0), report.get("losing_trades", 0),
             report.get("risk_stop_triggered", 0)),
        )
        await db.commit()
