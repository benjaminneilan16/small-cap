"""
Hämtar dagliga kurser från Yahoo Finance.

Svenska aktier har suffixet .ST — till exempel ENEA.ST.

VIKTIG BEGRÄNSNING: Yahoos täckning av First North och de minsta
listorna är ojämn. Vissa bolag saknas helt, andra har luckor. Koden
rapporterar därför exakt vilka tickers som fungerade, så att du kan
bygga universum utifrån vad som faktiskt går att hämta.

VAD VI INTE FÅR: orderboksdata. Den finns inte gratis för svenska
småbolag. Det får en direkt konsekvens för hur fills simuleras — se
paper.py.
"""
import logging
from datetime import datetime, timezone

from .store import connect, get_bars
from .config import UNIVERSE_FILE

logger = logging.getLogger("data")


def read_universe() -> list[str]:
    """
    Läser tickers från universe.txt.

    En ticker per rad. Rader som börjar med # ignoreras, så du kan
    kommentera bort bolag utan att radera dem.
    """
    if not UNIVERSE_FILE.exists():
        return []
    tickers = []
    for line in UNIVERSE_FILE.read_text(encoding="utf-8").splitlines():
        line = line.split("#")[0].strip().upper()
        if not line:
            continue
        if "." not in line:
            line = f"{line}.ST"
        tickers.append(line)
    return tickers


def sync_universe():
    """Lägger in tickers från filen i databasen."""
    tickers = read_universe()
    with connect() as c:
        for t in tickers:
            c.execute("INSERT OR IGNORE INTO universe (ticker) VALUES (?)", (t,))
        # Ta bort tickers som inte längre finns i filen
        placeholders = ",".join("?" * len(tickers)) if tickers else "''"
        c.execute(f"DELETE FROM universe WHERE ticker NOT IN ({placeholders})",
                  tickers if tickers else [])
    return tickers


def fetch(ticker: str, period: str = "2y") -> dict:
    """Hämtar historik för en ticker och sparar."""
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
    with connect() as c:
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


def update_all(period: str = "2y") -> dict:
    """
    Hämtar data för alla tickers och markerar vilka som duger.

    Under 100 staplar går inte att bedöma mönster på — de markeras som
    oanvändbara men ligger kvar i listan så du ser att de försökts.
    """
    tickers = sync_universe()
    if not tickers:
        return {"error": "universe.txt är tom — lägg till tickers först"}

    ok, failed = [], []
    now = datetime.now(timezone.utc).isoformat()

    for t in tickers:
        result = fetch(t, period)
        bars_in_db = len(get_bars(t, 10_000))
        usable = bars_in_db >= 100
        note = f"{bars_in_db} staplar"
        if result.get("error"):
            note += f" — {result['error']}"

        with connect() as c:
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


def usable_tickers() -> list[str]:
    with connect() as c:
        rows = c.execute(
            "SELECT ticker FROM universe WHERE data_ok = 1 ORDER BY ticker"
        ).fetchall()
    return [r["ticker"] for r in rows]
