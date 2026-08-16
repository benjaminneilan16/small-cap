"""
Intradagsreaktion — se ett fall eskalera INNAN nästa kvällskörning.

VARFÖR DET HÄR BEHÖVS: den dagliga körningen ser bara gårdagens
stängning. Om en aktie gappar ner kraftigt på förmiddagen och
fortsätter falla, ligger en liggande köporder kvar orörd tills kvällen
— då kan den redan ha fyllts mitt i ett fritt fall. Det här är
Marja-metodens verkliga styrka (hon ser det hända och kan reagera i
sekunder) som den dagliga cykeln inte kan efterlikna.

VAD DET HÄR FAKTISKT GÖR, OCH INTE GÖR:
Vi hämtar 5-minutersstaplar (Yahoo Finance, gratis, senaste ~60
dagarna) för bolag med öppna köpordrar, och drar tillbaka en order om
priset fallit mer än INTRADAY_PULLBACK_PCT under limitpriset SEDAN
ordern lades — innan den hinner fyllas i den kvällskörning som annars
skulle ha accepterat fyllnaden blint.

Det här är fortfarande INTE realtidsdata eller en riktig orderbok.
5-minutersstaplar med viss fördröjning är fortfarande en approximation
— bara en mycket färskare approximation än gårdagens stängning.

KÖRS SEPARAT från både morgonkoll och daglig körning, tänkt att köras
några gånger under handelsdagen (t.ex. varannan timme) för att fånga
eskalerande fall i tid.
"""
import logging
from datetime import datetime, timezone

from .store import connect, get_intraday_bars, prune_intraday_bars
from . import config

logger = logging.getLogger("intraday")


def fetch_intraday(ticker: str, market: str = "se") -> dict:
    """Hämtar färska intradagsstaplar för en ticker."""
    try:
        import yfinance as yf
    except ImportError:
        return {"ticker": ticker, "bars": 0, "error": "yfinance saknas"}

    cfg = config.get_config(market)
    try:
        hist = yf.Ticker(ticker).history(
            period=cfg.intraday_period,
            interval=cfg.intraday_interval,
            auto_adjust=False,
        )
    except Exception as e:
        return {"ticker": ticker, "bars": 0, "error": str(e)[:120]}

    if hist is None or hist.empty:
        return {"ticker": ticker, "bars": 0, "error": "ingen data"}

    rows = 0
    skipped = 0
    with connect(market) as c:
        for idx, r in hist.iterrows():
            try:
                open_ = float(r["Open"])
                high = float(r["High"])
                low = float(r["Low"])
                close = float(r["Close"])
            except (ValueError, TypeError, KeyError):
                skipped += 1
                continue

            # Samma NaN-skydd som i data.py — Yahoo kan returnera
            # ofullständiga rader, särskilt runt handelsstopp.
            if any(v != v for v in (open_, high, low, close)):
                skipped += 1
                continue
            if close <= 0:
                skipped += 1
                continue

            volume = float(r["Volume"]) if r["Volume"] == r["Volume"] else None
            c.execute(
                "INSERT OR REPLACE INTO intraday_bars "
                "(ticker, timestamp, open, high, low, close, volume) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (ticker, idx.isoformat(), open_, high, low, close, volume),
            )
            rows += 1

    if skipped:
        logger.warning("%s: hoppade över %d intradagsrad(er)", ticker, skipped)

    return {"ticker": ticker, "bars": rows}


def check_pullback_withdrawals(market: str = "se") -> list[dict]:
    """
    Kollar alla öppna köpordrar mot intradagsdata. Om priset fallit
    mer än intraday_pullback_pct under limitpriset SEDAN ordern
    lades, dras ordern tillbaka.

    Detta är medvetet ett FÖRSIKTIGT drag, inte ett aggressivt: vi
    drar bara tillbaka om röreslen är stor (standard 8%), inte vid
    normala dagsrörelser. Målet är att undvika de mest uppenbara
    "fylld mitt i ett fritt
