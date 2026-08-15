"""
Lagring i SQLite-filer som ligger i repot.

VARFÖR INGEN RIKTIG DATABAS: strategin körs en gång per dygn och
hanterar kanske tjugo bolag. Det är några tusen rader totalt. Att sätta
upp en molndatabas för det vore att lösa ett problem du inte har — och
det innebär anslutningssträngar, konton och en gratisnivå som kan
försvinna.

Med SQLite i repot får du istället:
  - Ingen registrering, inga hemligheter att hantera
  - Git-historiken som revisionslogg: varje körning syns som en commit
  - Möjlighet att ladda ner filen och öppna den lokalt när du vill
  - Gratis för alltid

TVÅ MARKNADER, TVÅ DATABASER: svenska och amerikanska bolag hålls
fysiskt separerade i olika filer (market_se.db / market_us.db), inte
bara filtrerade inom samma fil. Det gör det omöjligt att kapital eller
positioner från en marknad av misstag räknas in i den andra — en bugg
i en WHERE-sats kan inte blanda ihop kronor och dollar.
"""
import sqlite3
from pathlib import Path
from contextlib import contextmanager

DATA_DIR = Path(__file__).parent.parent / "data"

VALID_MARKETS = ("se", "us")


def _db_path(market: str) -> Path:
    if market not in VALID_MARKETS:
        raise ValueError(f"okänd marknad '{market}', förväntade en av {VALID_MARKETS}")
    return DATA_DIR / f"market_{market}.db"


@contextmanager
def connect(market: str = "se"):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(_db_path(market))
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


SCHEMA = """
CREATE TABLE IF NOT EXISTS universe (
    ticker       TEXT PRIMARY KEY,
    data_ok      INTEGER NOT NULL DEFAULT 0,
    bars         INTEGER DEFAULT 0,
    last_checked TEXT,
    note         TEXT
);

CREATE TABLE IF NOT EXISTS bars (
    ticker TEXT NOT NULL,
    date   TEXT NOT NULL,
    open   REAL NOT NULL,
    high   REAL NOT NULL,
    low    REAL NOT NULL,
    close  REAL NOT NULL,
    volume REAL,
    PRIMARY KEY (ticker, date)
);
CREATE INDEX IF NOT EXISTS idx_bars_ticker_date ON bars (ticker, date DESC);

CREATE TABLE IF NOT EXISTS account (
    id               INTEGER PRIMARY KEY CHECK (id = 1),
    cash             REAL NOT NULL,
    starting_capital REAL NOT NULL,
    created_at       TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS orders (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker        TEXT NOT NULL,
    side          TEXT NOT NULL,
    limit_price   REAL NOT NULL,
    shares        REAL NOT NULL,
    placed_date   TEXT NOT NULL,
    status        TEXT NOT NULL DEFAULT 'open',
    filled_date   TEXT,
    fill_price    REAL,
    gap_pct       REAL,
    cancel_reason TEXT,
    position_id   INTEGER
);
CREATE INDEX IF NOT EXISTS idx_orders_status ON orders (status, ticker);

CREATE TABLE IF NOT EXISTS positions (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker          TEXT NOT NULL,
    shares          REAL NOT NULL,
    entry_price     REAL NOT NULL,
    entry_date      TEXT NOT NULL,
    target_price    REAL NOT NULL,
    commission_paid REAL NOT NULL DEFAULT 0,
    status          TEXT NOT NULL DEFAULT 'open',
    exit_price      REAL,
    exit_date       TEXT,
    exit_reason     TEXT,
    realized_pnl    REAL,
    mae_pct         REAL,
    days_held       INTEGER,
    gap_pct         REAL
);
CREATE INDEX IF NOT EXISTS idx_positions_status ON positions (status);

CREATE TABLE IF NOT EXISTS runs (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    run_at    TEXT NOT NULL,
    kind      TEXT NOT NULL DEFAULT 'daily',
    fills     INTEGER DEFAULT 0,
    exits     INTEGER DEFAULT 0,
    cancels   INTEGER DEFAULT 0,
    orders_placed INTEGER DEFAULT 0,
    total_value   REAL,
    note      TEXT
);
"""


def init(market: str = "se"):
    with connect(market) as c:
        c.executescript(SCHEMA)


def init_account(capital: float, market: str = "se"):
    from datetime import datetime, timezone
    with connect(market) as c:
        c.execute(
            "INSERT OR IGNORE INTO account (id, cash, starting_capital, created_at) "
            "VALUES (1, ?, ?, ?)",
            (capital, capital, datetime.now(timezone.utc).isoformat()),
        )


def reset_account(capital: float, market: str = "se"):
    from datetime import datetime, timezone
    with connect(market) as c:
        c.execute("DELETE FROM orders")
        c.execute("DELETE FROM positions")
        c.execute("DELETE FROM runs")
        c.execute(
            "INSERT OR REPLACE INTO account (id, cash, starting_capital, created_at) "
            "VALUES (1, ?, ?, ?)",
            (capital, capital, datetime.now(timezone.utc).isoformat()),
        )


def get_cash(market: str = "se") -> float:
    with connect(market) as c:
        row = c.execute("SELECT cash FROM account WHERE id = 1").fetchone()
    return float(row["cash"]) if row else 0.0


def get_bars(ticker: str, limit: int = 400, market: str = "se") -> list[dict]:
    with connect(market) as c:
        rows = c.execute(
            "SELECT date, open, high, low, close, volume FROM bars "
            "WHERE ticker = ? ORDER BY date DESC LIMIT ?",
            (ticker, limit),
        ).fetchall()
    return [dict(r) for r in reversed(rows)]
