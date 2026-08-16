"""
Lagring i SQLite-filer som ligger i repot.

VARFOR INGEN RIKTIG DATABAS: strategin kors en gang per dygn och
hanterar kanske tjugo bolag.

Med SQLite i repot far du istallet:
  - Ingen registrering, inga hemligheter att hantera
  - Git-historiken som revisionslogg
  - Mojlighet att ladda ner filen och oppna den lokalt nar du vill
  - Gratis for alltid

TVA MARKNADER, TVA DATABASER: svenska och amerikanska bolag halls
fysiskt separerade i olika filer.
"""
import sqlite3
from pathlib import Path
from contextlib import contextmanager

DATA_DIR = Path(__file__).parent.parent / "data"

VALID_MARKETS = ("se", "us", "se_bt", "us_bt")


def _base_market(market: str) -> str:
    """se_bt -> se, us_bt -> us, se/us oforandrat."""
    return market.removesuffix("_bt")


def _db_path(market: str) -> Path:
    if market not in VALID_MARKETS:
        raise ValueError(f"okand marknad '{market}', forvantade en av {VALID_MARKETS}")
    return DATA_DIR / f"market_{market}.db"


@contextmanager
def connect(market: str = "se"):
    """
    Ger en databasanslutning for en marknad. Atervander EN anslutning
    per marknad inom samma process for prestanda.
    """
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = _CONNECTIONS.get(market)
    if conn is None:
        conn = sqlite3.connect(_db_path(market), check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        _CONNECTIONS[market] = conn
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise


_CONNECTIONS: dict[str, sqlite3.Connection] = {}


def close_all():
    """
    Stanger alla oppna databasanslutningar. MASTE koras innan git
    committar databasfilerna -- annars kan senaste datan sitta kvar i
    en -wal-sidofil som aldrig nar git.
    """
    for conn in _CONNECTIONS.values():
        try:
            conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        except Exception:
            pass
        conn.close()
    _CONNECTIONS.clear()


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

CREATE TABLE IF NOT EXISTS intraday_bars (
    ticker    TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    open      REAL NOT NULL,
    high      REAL NOT NULL,
    low       REAL NOT NULL,
    close     REAL NOT NULL,
    volume    REAL,
    PRIMARY KEY (ticker, timestamp)
);
CREATE INDEX IF NOT EXISTS idx_intraday_ticker_ts ON intraday_bars (ticker, timestamp DESC);

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
    position_id   INTEGER,
    adjustments_count INTEGER NOT NULL DEFAULT 0,
    original_limit_price REAL
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
        _migrate(c)


def _migrate(c):
    """
    Lagger till kolumner som saknas i redan existerande databaser.

    CREATE TABLE IF NOT EXISTS andrar inte en tabell som redan finns.
    Nya kolumner som adjustments_count maste darfor laggas till
    explicit har, annars kraschar koden mot din redan korande
    produktionsdatabas.
    """
    existing = {row["name"] for row in
               c.execute("PRAGMA table_info(orders)").fetchall()}
    if "adjustments_count" not in existing:
        c.execute("ALTER TABLE orders ADD COLUMN adjustments_count "
                  "INTEGER NOT NULL DEFAULT 0")
    if "original_limit_price" not in existing:
        c.execute("ALTER TABLE orders ADD COLUMN original_limit_price REAL")


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


def get_intraday_bars(ticker: str, since: str | None = None,
                       market: str = "se") -> list[dict]:
    """
    Hamtar intradagsstaplar for en ticker, aldst forst.
    """
    with connect(market) as c:
        if since:
            rows = c.execute(
                "SELECT timestamp, open, high, low, close, volume "
                "FROM intraday_bars WHERE ticker = ? AND timestamp > ? "
                "ORDER BY timestamp", (ticker, since),
            ).fetchall()
        else:
            rows = c.execute(
                "SELECT timestamp, open, high, low, close, volume "
                "FROM intraday_bars WHERE ticker = ? ORDER BY timestamp",
                (ticker,),
            ).fetchall()
    return [dict(r) for r in rows]


def prune_intraday_bars(older_than_days: int = 3, market: str = "se") -> int:
    """
    Rensar gamla intradagsstaplar.
    """
    from datetime import datetime, timezone, timedelta
    cutoff = (datetime.now(timezone.utc) - timedelta(days=older_than_days)).isoformat()
    with connect(market) as c:
        cur = c.execute("DELETE FROM intraday_bars WHERE timestamp < ?", (cutoff,))
        return cur.rowcount
