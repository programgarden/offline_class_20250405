import aiosqlite
import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS stock_analysis (
    id INTEGER PRIMARY KEY,
    analysis_date TEXT NOT NULL,
    symbol TEXT NOT NULL,
    exchange_code TEXT NOT NULL,
    company_name TEXT,
    momentum_score REAL,
    financial_score REAL,
    total_score REAL,
    selected INTEGER DEFAULT 0,
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS trades (
    id INTEGER PRIMARY KEY,
    symbol TEXT NOT NULL,
    exchange_code TEXT NOT NULL,
    order_type TEXT NOT NULL,
    order_no TEXT,
    quantity INTEGER NOT NULL,
    price REAL NOT NULL,
    amount REAL NOT NULL,
    reason TEXT,
    is_dry_run INTEGER DEFAULT 0,
    executed_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS positions (
    id INTEGER PRIMARY KEY,
    symbol TEXT NOT NULL UNIQUE,
    exchange_code TEXT NOT NULL,
    quantity INTEGER NOT NULL,
    avg_buy_price REAL NOT NULL,
    highest_price REAL NOT NULL,
    trailing_stop_price REAL NOT NULL,
    atr REAL NOT NULL,
    entry_date TEXT NOT NULL,
    updated_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS daily_reports (
    id INTEGER PRIMARY KEY,
    report_date TEXT NOT NULL UNIQUE,
    starting_balance REAL,
    ending_balance REAL,
    daily_pnl REAL,
    daily_pnl_rate REAL,
    total_trades INTEGER,
    winning_trades INTEGER,
    losing_trades INTEGER,
    risk_stop_triggered INTEGER DEFAULT 0,
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    description TEXT,
    updated_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS futures_positions (
    id INTEGER PRIMARY KEY,
    symbol TEXT NOT NULL UNIQUE,
    base_symbol TEXT NOT NULL,
    direction TEXT NOT NULL,
    quantity INTEGER NOT NULL,
    avg_entry_price REAL NOT NULL,
    highest_price REAL NOT NULL,
    lowest_price REAL NOT NULL,
    trailing_stop_price REAL NOT NULL,
    atr REAL NOT NULL,
    tick_size REAL NOT NULL,
    tick_value REAL NOT NULL,
    entry_date TEXT NOT NULL,
    updated_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS futures_trades (
    id INTEGER PRIMARY KEY,
    symbol TEXT NOT NULL,
    base_symbol TEXT NOT NULL,
    direction TEXT NOT NULL,
    order_type TEXT NOT NULL,
    order_no TEXT,
    quantity INTEGER NOT NULL,
    price REAL NOT NULL,
    pnl REAL,
    reason TEXT,
    executed_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS futures_daily_reports (
    id INTEGER PRIMARY KEY,
    report_date TEXT NOT NULL UNIQUE,
    starting_equity REAL,
    ending_equity REAL,
    daily_pnl REAL,
    daily_pnl_rate REAL,
    margin_used REAL,
    margin_rate REAL,
    total_trades INTEGER,
    winning_trades INTEGER,
    losing_trades INTEGER,
    risk_stop_triggered INTEGER DEFAULT 0,
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS futures_specs (
    base_symbol TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    exchange TEXT NOT NULL,
    tick_size REAL NOT NULL,
    tick_value REAL NOT NULL,
    margin_required REAL,
    updated_at TEXT DEFAULT (datetime('now'))
);
"""

DEFAULTS = {
    "mode": (config.DEFAULT_MODE, "운영 모드 (dry/live)"),
    "donchian_period": (str(config.DONCHIAN_PERIOD), "돈치안 채널 기간"),
    "atr_multiplier": (str(config.ATR_MULTIPLIER), "트레일링 스탑 ATR 배수"),
    "max_stocks": (str(config.MAX_STOCKS), "최대 보유 종목 수"),
    "capital_ratio": (str(config.CAPITAL_RATIO), "예수금 사용 비율(%)"),
    "trading_paused": ("0", "매매 일시 중단 여부"),
    "risk_stopped": ("0", "리스크 청산으로 당일 매매 중단 여부"),
    # 선물 설정
    "futures_donchian_period": (str(config.FUTURES_DONCHIAN_PERIOD), "선물 돈치안 채널 기간"),
    "futures_atr_multiplier": (str(config.FUTURES_ATR_MULTIPLIER), "선물 트레일링 스탑 ATR 배수"),
    "futures_max_contracts": (str(config.FUTURES_MAX_CONTRACTS), "선물 최대 동시 보유 종목 수"),
    "futures_risk_per_trade": (str(config.FUTURES_RISK_PER_TRADE), "선물 1종목당 리스크 비율(%)"),
    "futures_trading_paused": ("0", "선물 매매 일시 중단 여부"),
    "futures_risk_stopped": ("0", "선물 리스크 청산으로 당일 매매 중단 여부"),
}


async def init_db():
    async with aiosqlite.connect(config.DB_PATH) as db:
        await db.executescript(SCHEMA)
        for key, (value, desc) in DEFAULTS.items():
            await db.execute(
                "INSERT OR IGNORE INTO settings (key, value, description) VALUES (?, ?, ?)",
                (key, value, desc),
            )
        await db.commit()
