"""
Intradagsreaktion -- se ett fall eskalera INNAN nasta kvallskorning.

VARFOR DET HAR BEHOVS: den dagliga korningen ser bara gardagens
stangning. Om en aktie gappar ner kraftigt pa formiddagen och
fortsatter falla, ligger en liggande koporder kvar orord tills kvallen
-- da kan den redan ha fyllts mitt i ett fritt fall.

VAD DET HAR FAKTISKT GOR, OCH INTE GOR:
Vi hamtar 5-minutersstaplar (Yahoo Finance, gratis, senaste ~60
dagarna) for bolag med oppna koporder. Tre lagen baserat pa hur mycket
priset fallit sedan ordern lades:

  1. Under intraday_adjust_pct (t.ex. 4%): normal dagsrorelse, ingen
     atgard.
  2. Mellan intraday_adjust_pct och intraday_pullback_pct (4-8%):
     JUSTERA limitpriset nedat for att folja kursen -- se
     adjust_orders().
  3. Over intraday_pullback_pct (8%): DRA TILLBAKA ordern helt -- se
     check_pullback_withdrawals().

Det har ar fortfarande INTE realtidsdata eller en riktig orderbok --
bara en mycket farskare approximation an gardagens stangning.
"""
import logging
from datetime import datetime, timezone

from .store import connect, get_intraday_bars, prune_intraday_bars
from . import config

logger = logging.getLogger("intraday")


def fetch_intraday(ticker: str, market: str = "se") -> dict:
    """Hamtar farska intradagsstaplar for en ticker."""
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
        logger.warning("%s: hoppade over %d intradagsrad(er)", ticker, skipped)

    return {"ticker": ticker, "bars": rows}


def adjust_orders(market: str = "se") -> list[dict]:
    """
    Justerar limitpriset nedat for ordrar som fallit mattligt intradag
    -- mellan intraday_adjust_pct och intraday_pullback_pct under
    limitpriset sedan ordern lades.

    VARFOR EN MELLANNIVA MELLAN "GOR INGET" OCH "DRA TILLBAKA": att
    bara ha tva lagen missar precis den situation Marja sjalv beskriver
    -- att aktivt folja med i en rorelse och lagga om ordern dar
    koparna faktiskt ar NU.

    VARFOR DET FINNS ETT TAK (intraday_max_adjustments): utan en grans
    skulle en aktie i jamn, ihallande nedgang kunna fa ordern justerad
    om och om igen hela vagen ner -- i praktiken samma sak som att jaga
    kursen nedat. Nar taket nas gar ordern istallet till vanlig
    pullback-tillbakadragning pa nasta kontroll.

    Ordning i run_intraday_check(): justering kors FORE tillbaka-
    dragning, sa en order som redan justerat sig ner till en ny,
    rimlig niva inte omedelbart bedoms mot sitt URSPRUNGLIGA pris.
    """
    cfg = config.get_config(market)

    with connect(market) as c:
        orders = c.execute(
            "SELECT id, ticker, limit_price, placed_date, adjustments_count, "
            "original_limit_price FROM orders WHERE status = 'open' AND side = 'buy'"
        ).fetchall()

    adjusted = []
    for o in orders:
        ticker = o["ticker"]
        limit_price = float(o["limit_price"])
        adjustments_count = o["adjustments_count"] or 0

        if adjustments_count >= cfg.intraday_max_adjustments:
            continue

        fetch_intraday(ticker, market)

        since = f"{o['placed_date']}T00:00:00"
        bars = get_intraday_bars(ticker, since=since, market=market)
        if not bars:
            continue

        lowest = min(float(b["low"]) for b in bars)
        drop_pct = (limit_price - lowest) / limit_price * 100

        if drop_pct <= cfg.intraday_adjust_pct or drop_pct > cfg.intraday_pullback_pct:
            continue

        new_limit = round(lowest * (1 - cfg.intraday_adjust_below_pct / 100), 4)
        original = o["original_limit_price"] or limit_price

        with connect(market) as c:
            c.execute(
                "UPDATE orders SET limit_price = ?, adjustments_count = ?, "
                "original_limit_price = ? WHERE id = ?",
                (new_limit, adjustments_count + 1, original, o["id"]),
            )

        adjusted.append({
            "ticker": ticker,
            "old_limit": limit_price,
            "new_limit": new_limit,
            "drop_pct": round(drop_pct, 1),
            "adjustments_count": adjustments_count + 1,
        })
        logger.info("Justerade %s: %.2f -> %.2f (fallit %.1f%%, justering %d/%d)",
                   ticker, limit_price, new_limit, drop_pct,
                   adjustments_count + 1, cfg.intraday_max_adjustments)

    return adjusted


def check_pullback_withdrawals(market: str = "se") -> list[dict]:
    """
    Kollar alla oppna koporder mot intradagsdata. Om priset fallit
    mer an intraday_pullback_pct under limitpriset SEDAN ordern
    lades, dras ordern tillbaka.
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

        fetch_intraday(ticker, market)

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
                    (f"intradagsfall {drop_pct:.1f}% - drogs tillbaka", o["id"]),
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


def detect_volume_spike(ticker: str, market: str = "se",
                         bars: list[dict] | None = None) -> dict | None:
    """
    Grov proxy for "nagot hande": onormal volym + stort prisfall samma
    dag.
    """
    cfg = config.get_config(market)
    needed = cfg.volume_spike_lookback_days + 1

    if bars is None:
        from .store import get_bars
        bars = get_bars(ticker, needed, market)
    elif len(bars) > needed:
        bars = bars[-needed:]

    if len(bars) < needed:
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
    Huvudfunktion: justerar ordrar som fallit mattligt, drar tillbaka
    ordrar som fallit kraftigt, stadar gammal intradagsdata.

    ORDNING SPELAR ROLL: justering kors FORE tillbakadragning.
    """
    adjusted = adjust_orders(market)
    withdrawn = check_pullback_withdrawals(market)
    pruned = prune_intraday_bars(market=market)
    return {"adjusted": adjusted, "withdrawn": withdrawn, "pruned_rows": pruned}
