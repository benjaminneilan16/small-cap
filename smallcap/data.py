"""
Hämtar dagliga kurser från Yahoo Finance.

Svenska aktier har suffixet .ST — till exempel ENEA.ST. Amerikanska
aktier har inget suffix — till exempel AAPL.

VIKTIG BEGRÄNSNING: Yahoos täckning av First North och de minsta
listorna är ojämn. Vissa bolag saknas helt, andra har luckor. Koden
rapporterar därför exakt vilka tickers som fungerade, så att du kan
bygga universum utifrån vad som faktiskt går att hämta. Samma gäller
för de mest illikvida amerikanska small caps.

VAD VI INTE FÅR: orderboksdata. Den finns inte gratis för svenska
småbolag eller amerikanska small caps. Det får en direkt konsekvens
för hur fills simuleras — se paper.py.
"""
import logging
from datetime import datetime, timezone

from .store import connect, get_bars
from .config import get_config

logger = logging.getLogger("data")


def read_universe(market: str = "se") -> list[str]:
    """
    Läser tickers från universe.txt (SE) eller universe_us.txt (US).

    En ticker per rad. Rader som börjar med # ignoreras, så du kan
    kommentera bort bolag utan att radera dem. För SE läggs .ST på
    automatiskt om det saknas. För US läggs inget suffix på.
    """
    cfg = get_config(market)
    if not cfg.universe_file.exists():
        return []
    tickers = []
    for line in cfg.universe_file.read_text(encoding="utf-8").splitlines():
        line = line.split("#")[0].strip().upper()
        if not line:
            continue
        if cfg.ticker_suffix and cfg.ticker_suffix not in line and "." not in line:
            line = f"{line}{cfg.ticker_suffix}"
        tickers.append(line)
    return tickers


def sync_universe(market: str = "se"):
    """Lägger in tickers från filen i databasen för given marknad."""
    tickers = read_universe(market)
    with connect(market) as c:
        for t in tickers:
            c.execute("INSERT OR IGNORE INTO universe (ticker) VALUES (?)", (t,))
        # Ta bort tickers som inte längre finns i filen
        placeholders = ",".join("?" * len(tickers)) if tickers else "''"
        c.execute(f"DELETE FROM universe WHERE ticker NOT IN ({placeholders})",
                  tickers if tickers else [])
    return tickers


def fetch(ticker: str, period: str = "2y", market: str = "se") -> dict:
    """Hämtar historik för en ticker och sparar i rätt marknads databas."""
    try:
        import yfinance as yf
    except ImportError:
        return {"ticker": ticker, "bars": 0, "error": "yfinance saknas"}

    try:
        hist = yf.Ticker(ticker).history(period=period, interval="1d",
                                          auto_adjust=False)
    except Exception as e:
        return {"ticker": ticker, "bars": 0, "error": str(e)[:120]}

    if hist is None or hist.empty:
        return {"ticker": ticker, "bars": 0, "error": "ingen data"}

    rows = 0
    with connect(market) as c:
        for idx, r in hist.iterrows():
            try:
                close = float(r["Close"])
                if close <= 0:
                    continue
                c.execute(
                    "INSERT OR REPLACE INTO bars "
                    "(ticker, date, open, high, low, close, volume) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (ticker, idx.date().isoformat(), float(r["Open"]),
                     float(r["High"]), float(r["Low"]), close,
                     float(r["Volume"]) if r["Volume"] == r["Volume"] else None),
                )
                rows += 1
            except (ValueError, TypeError, KeyError):
                continue

    return {"ticker": ticker, "bars": rows}


def update_all(period: str = "2y", market: str = "se") -> dict:
    """
    Hämtar data för alla tickers på given marknad och markerar vilka
    som duger.

    Under 100 staplar går inte att bedöma mönster på — de markeras som
    oanvändbara men ligger kvar i listan så du ser att de försökts.
    """
    tickers = sync_universe(market)
    if not tickers:
        cfg = get_config(market)
        return {"error": f"{cfg.universe_file.name} är tom — lägg till tickers först"}

    ok, failed = [], []
    now = datetime.now(timezone.utc).isoformat()

    for t in tickers:
        result = fetch(t, period, market)
        bars_in_db = len(get_bars(t, 10_000, market))
        usable = bars_in_db >= 100
        note = f"{bars_in_db} staplar"
        if result.get("error"):
            note += f" — {result['error']}"

        with connect(market) as c:
            c.execute(
                "UPDATE universe SET data_ok = ?, bars = ?, last_checked = ?, note = ? "
                "WHERE ticker = ?",
                (1 if usable else 0, bars_in_db, now, note, t),
            )

        (ok if usable else failed).append({"ticker": t, "bars": bars_in_db,
                                           "error": result.get("error")})
        logger.info("%-14s %4d staplar%s", t, bars_in_db,
                    f"  ({result['error']})" if result.get("error") else "")

    return {"usable": len(ok), "unusable": len(failed), "ok": ok, "failed": failed}


def usable_tickers(market: str = "se") -> list[str]:
    with connect(market) as c:
        rows = c.execute(
            "SELECT ticker FROM universe WHERE data_ok = 1 ORDER BY ticker"
        ).fetchall()
    return [r["ticker"] for r in rows]
