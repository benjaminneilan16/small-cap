"""
Screener -- hittar bolag som passar spread-strategin.

VAD VI LETAR EFTER, oversatt fran hennes egna ord:

  "stora spreadar, stora upp- och nedgangar per dag och per vecka"
      -> stort dagligt spann i procent

  "kursen blir valdigt spretig"
      -> LAG efficiency ratio. Priset ror sig mycket men kommer ingenstans.

  "Hur har den studsat forut? Ser jag tydliga nivaer?"
      -> priset atervander till samma nivaer om och om igen

DEN VIKTIGASTE INSIKTEN: strategin vill ha det som konventionell analys
kallar daligt. Bred spread och spretig kurs ar normalt varningstecken.
Har ar de sjalva ravaran. En aktie som trendar snyggt uppat ar vardelos
-- det finns inga studsar att fanga.

MARKNADSOBEROENDE: monstret hon beskriver ar inte specifikt for svenska
smabolag -- samma logik (spread, oscillation, atervandande nivaer)
galler for illikvida amerikanska small caps. Bara valutan och
omsattningstroskeln skiljer, och de kommer fran MarketConfig.
"""
import logging
import statistics

from .store import get_bars
from .data import usable_tickers
from .config import get_config

logger = logging.getLogger("screener")


def efficiency_ratio(closes: list[float], period: int = 20) -> float | None:
    """
    Kaufmans Efficiency Ratio: nettororelse delat med summan av alla
    enskilda rorelser.

      nara 1,0 = priset gick rakt fran A till B (trend)
      nara 0,0 = priset rorde sig mycket men kom ingenstans (oscillation)

    For den har strategin vill vi ha LAGT varde.
    """
    if len(closes) < period + 1:
        return None
    w = closes[-(period + 1):]
    net = abs(w[-1] - w[0])
    total = sum(abs(w[i] - w[i - 1]) for i in range(1, len(w)))
    return 0.0 if total == 0 else net / total


def find_levels(bars: list[dict], bins: int = 20) -> list[dict]:
    """
    Hittar prisnivaer dar aktien handlat ofta.

    Metoden: dela prisintervallet i lador och rakna hur manga dagar som
    berort varje lada. Nivaer med manga traffar ar dar handeln
    koncentrerats -- dit priset tenderar att atervanda.
    """
    if len(bars) < 40:
        return []

    lo = min(float(b["low"]) for b in bars)
    hi = max(float(b["high"]) for b in bars)
    if hi <= lo:
        return []

    width = (hi - lo) / bins
    counts = [0] * bins

    for b in bars:
        start = max(0, min(bins - 1, int((float(b["low"]) - lo) / width)))
        end = max(0, min(bins - 1, int((float(b["high"]) - lo) / width)))
        for i in range(start, end + 1):
            counts[i] += 1

    total = sum(counts) or 1
    levels = [
        {
            "price": round(lo + width * (i + 0.5), 4),
            "touches": c,
            "share_pct": round(c / total * 100, 2),
        }
        for i, c in enumerate(counts)
    ]
    levels.sort(key=lambda x: x["touches"], reverse=True)
    return levels


def analyze(ticker: str, lookback: int = 250, market: str = "se",
           skip_volume_spike: bool = False) -> dict:
    cfg = get_config(market)
    bars = get_bars(ticker, lookback, market)
    if len(bars) < 100:
        return {"ticker": ticker, "usable": False,
                "reason": f"for lite data ({len(bars)} staplar)"}

    closes = [float(b["close"]) for b in bars]
    highs = [float(b["high"]) for b in bars]
    lows = [float(b["low"]) for b in bars]
    volumes = [float(b["volume"] or 0) for b in bars]

    ranges = [(h - l) / l * 100 for h, l in zip(highs, lows) if l > 0]
    median_range = statistics.median(ranges) if ranges else 0

    turnovers = [c * v for c, v in zip(closes, volumes)]
    median_turnover = statistics.median(turnovers) if turnovers else 0

    er_60 = efficiency_ratio(closes, 60)
    net_change = (closes[-1] - closes[0]) / closes[0] * 100

    levels = find_levels(bars)
    top_levels = levels[:5]
    revisit = sum(l["share_pct"] for l in top_levels)

    reasons = []
    usable = True

    if median_range < cfg.min_daily_range_pct:
        usable = False
        reasons.append(f"dagligt spann {median_range:.1f}% under "
                       f"{cfg.min_daily_range_pct}%")

    if median_turnover < cfg.min_daily_turnover:
        usable = False
        reasons.append(f"omsattning {median_turnover:,.0f} {cfg.currency}/dag for lag")

    if er_60 is not None and er_60 > cfg.max_efficiency_ratio:
        usable = False
        reasons.append(f"efficiency ratio {er_60:.2f} -- trendar, studsar inte")

    score = 0.0
    if median_range:
        score += min(median_range / cfg.min_daily_range_pct, 3.0)
    if er_60 is not None:
        score += (1 - min(er_60 / cfg.max_efficiency_ratio, 1.0)) * 2
    score += min(revisit / 40, 1.0)

    # Volymspik-flagga: grov proxy for "nagot hande nyligen".
    #
    # PRESTANDA: atervander `bars` som redan hamtats ovan istallet for
    # en ny databasfraga. Under backtest/walk-forward hoppas berak-
    # ningen helt over (skip_volume_spike=True) -- flaggan ar till for
    # att du manuellt ska kolla en LEVANDE kandidat innan du litar pa
    # den, vilket ar meningslost i en historisk simulering som kors
    # helt automatiskt utan manskllig granskning. Att randa ut den dar
    # kostade tidigare miljontals extra databasfragor per korning.
    volume_spike = None
    if not skip_volume_spike:
        from . import intraday as _intraday
        volume_spike = _intraday.detect_volume_spike(ticker, market, bars=bars)

    return {
        "ticker": ticker,
        "usable": usable,
        "score": round(score, 3),
        "bars": len(bars),
        "last_close": round(closes[-1], 4),
        "median_daily_range_pct": round(median_range, 2),
        "median_turnover": round(median_turnover, 0),
        "efficiency_ratio_60": round(er_60, 3) if er_60 is not None else None,
        "net_change_pct": round(net_change, 1),
        "top_levels": top_levels,
        "revisit_share_pct": round(revisit, 1),
        "reasons": reasons,
        "warning": _warning(net_change, median_turnover, cfg.currency),
        "volume_spike": volume_spike,
    }


def _warning(net_change: float, turnover: float, currency: str) -> str | None:
    """
    Varningar for fall som passerar filtren men anda ar farliga.

    Den viktigaste: en aktie som fallit 60% har ocksa lag efficiency
    ratio -- men av fel skal. Den oscillerar inte, den faller i etapper.
    Att kopa studsar dar ar att fanga en fallande kniv.
    """
    parts = []
    if net_change < -50:
        parts.append(
            f"Aktien ar ner {abs(net_change):.0f}% over perioden. Lag efficiency "
            "ratio kan bero pa att den faller i etapper snarare an oscillerar."
        )
    if turnover < 300_000:
        parts.append(
            f"Tunn omsattning ({turnover:,.0f} {currency}/dag) -- risk att bli fylld "
            "just nar nagon saljer av ett skal du inte kanner till."
        )
    return " ".join(parts) if parts else None


def screen_all(lookback: int = 250, market: str = "se",
               skip_volume_spike: bool = False) -> dict:
    tickers = usable_tickers(market)
    if not tickers:
        return {"error": "Inga validerade tickers. Kor datauppdateringen forst."}

    results = []
    for t in tickers:
        try:
            results.append(analyze(t, lookback, market,
                                   skip_volume_spike=skip_volume_spike))
        except Exception as e:
            logger.error("Analys misslyckades for %s: %s", t, e)

    candidates = [r for r in results if r.get("usable")]
    candidates.sort(key=lambda r: r["score"], reverse=True)
    rejected = [r for r in results if not r.get("usable")]

    return {"candidates": candidates, "rejected": rejected,
            "screened": len(results)}
