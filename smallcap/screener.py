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
    "fylld mitt i ett fritt fall"-scenarierna, inte att försöka
    tajma varje liten rörelse.
    """
    cfg = config.get_config(market)

    with connect(market) as c:
        orders = c.execute(
            "SELECT id, ticker, limit_price, placed_date FROM orders "
            "WHERE status = 'open' AND side = 'buy'"
        ).fetchall()

    withdrawn = []
    for o in orders:
        ticker = o["ticker"]
        limit_price = float(o["limit_price"])

        # Hämta färsk intradagsdata för just denna ticker
        fetch_intraday(ticker, market)

        # Bara staplar EFTER att ordern lades är relevanta
        since = f"{o['placed_date']}T00:00:00"
        bars = get_intraday_bars(ticker, since=since, market=market)
        if not bars:
            continue

        lowest = min(float(b["low"]) for b in bars)
        drop_pct = (limit_price - lowest) / limit_price * 100

        if drop_pct > cfg.intraday_pullback_pct:
            with connect(market) as c:
                c.execute(
                    "UPDATE orders SET status = 'cancelled', "
                    "cancel_reason = ? WHERE id = ?",
                    (f"intradagsfall {drop_pct:.1f}% — drogs tillbaka", o["id"]),
                )
            withdrawn.append({
                "ticker": ticker,
                "limit_price": limit_price,
                "lowest_seen": round(lowest, 4),
                "drop_pct": round(drop_pct, 1),
            })
            logger.info("Drog tillbaka %s: fallit %.1f%% under limit sedan ordern lades",
                       ticker, drop_pct)

    return withdrawn


def detect_volume_spike(ticker: str, market: str = "se") -> dict | None:
    """
    Grov proxy för "något hände": onormal volym + stort prisfall samma
    dag. Skiljer inte VAD som hände (nyheter, sektor-rörelse, ren
    spekulation) — bara ATT något avvek från det normala mönstret.

    Detta ersätter INTE mänsklig bedömning av varför en aktie rör sig
    (se README om varför det är svårt att kodifiera), men ger en
    enkel flagga att titta extra noga på innan man litar på ett fynd.
    """
    from .store import get_bars

    cfg = config.get_config(market)
    bars = get_bars(ticker, cfg.volume_spike_lookback_days + 1, market)
    if len(bars) < cfg.volume_spike_lookback_days + 1:
        return None

    *history, today = bars
    volumes = [float(b["volume"] or 0) for b in history]
    median_volume = sorted(volumes)[len(volumes) // 2] if volumes else 0
    today_volume = float(today["volume"] or 0)

    if median_volume <= 0:
        return None

    ratio = today_volume / median_volume
    price_change = (float(today["close"]) - float(today["open"])) / float(today["open"]) * 100

    if ratio >= cfg.volume_spike_multiplier:
        return {
            "ticker": ticker,
            "volume_ratio": round(ratio, 1),
            "price_change_pct": round(price_change, 1),
            "likely_news": ratio >= cfg.volume_spike_multiplier and price_change < -5,
        }
    return None


def run_intraday_check(market: str = "se") -> dict:
    """
    Huvudfunktion: kollar pullback-tillbakadragningar för alla öppna
    ordrar, städar gammal intradagsdata. Tänkt att köras några gånger
    under handelsdagen.
    """
    withdrawn = check_pullback_withdrawals(market)
    pruned = prune_intraday_bars(market=market)
    return {"withdrawn": withdrawn, "pruned_rows": pruned}
