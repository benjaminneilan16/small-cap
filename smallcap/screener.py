"""
Screener — hittar bolag som passar spread-strategin.

VAD VI LETAR EFTER, översatt från hennes egna ord:

  "stora spreadar, stora upp- och nedgångar per dag och per vecka"
      -> stort dagligt spann i procent

  "kursen blir väldigt spretig"
      -> LÅG efficiency ratio. Priset rör sig mycket men kommer ingenstans.

  "Hur har den studsat förut? Ser jag tydliga nivåer?"
      -> priset återvänder till samma nivåer om och om igen

DEN VIKTIGASTE INSIKTEN: strategin vill ha det som konventionell analys
kallar dåligt. Bred spread och spretig kurs är normalt varningstecken.
Här är de själva råvaran. En aktie som trendar snyggt uppåt är värdelös —
det finns inga studsar att fånga.

MARKNADSOBEROENDE: mönstret hon beskriver är inte specifikt för svenska
småbolag — samma logik (spread, oscillation, återkommande nivåer) gäller
för illikvida amerikanska small caps. Bara valutan och omsättnings-
tröskeln skiljer, och de kommer från MarketConfig.
"""
import logging
import statistics

from .store import get_bars
from .data import usable_tickers
from .config import get_config

logger = logging.getLogger("screener")


def efficiency_ratio(closes: list[float], period: int = 20) -> float | None:
    """
    Kaufmans Efficiency Ratio: nettorörelse delat med summan av alla
    enskilda rörelser.

      nära 1,0 = priset gick rakt från A till B (trend)
      nära 0,0 = priset rörde sig mycket men kom ingenstans (oscillation)

    För den här strategin vill vi ha LÅGT värde.
    """
    if len(closes) < period + 1:
        return None
    w = closes[-(period + 1):]
    net = abs(w[-1] - w[0])
    total = sum(abs(w[i] - w[i - 1]) for i in range(1, len(w)))
    return 0.0 if total == 0 else net / total


def find_levels(bars: list[dict], bins: int = 20) -> list[dict]:
    """
    Hittar prisnivåer där aktien handlat ofta.

    Metoden: dela prisintervallet i lådor och räkna hur många dagar som
    berört varje låda. Nivåer med många träffar är där handeln
    koncentrerats — dit priset tenderar att återvända.
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


def analyze(ticker: str, lookback: int = 250, market: str = "se") -> dict:
    cfg = get_config(market)
    bars = get_bars(ticker, lookback, market)
    if len(bars) < 100:
        return {"ticker": ticker, "usable": False,
                "reason": f"för lite data ({len(bars)} staplar)"}

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
        reasons.append(f"omsättning {median_turnover:,.0f} {cfg.currency}/dag för låg")

    if er_60 is not None and er_60 > cfg.max_efficiency_ratio:
        usable = False
        reasons.append(f"efficiency ratio {er_60:.2f} — trendar, studsar inte")

    score = 0.0
    if median_range:
        score += min(median_range / cfg.min_daily_range_pct, 3.0)
    if er_60 is not None:
        score += (1 - min(er_60 / cfg.max_efficiency_ratio, 1.0)) * 2
    score += min(revisit / 40, 1.0)

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
    }


def _warning(net_change: float, turnover: float, currency: str) -> str | None:
    """
    Varningar för fall som passerar filtren men ändå är farliga.

    Den viktigaste: en aktie som fallit 60% har också låg efficiency
    ratio — men av fel skäl. Den oscillerar inte, den faller i etapper.
    Att köpa studsar där är att fånga en fallande kniv.

    Tröskeln 300 000 för "tunn omsättning" är i lokal valuta (kr eller
    dollar). Det är en grov tumregel snarare än ett exakt likvärde
    mellan marknader — poängen är att flagga bolag nära screenerns
    egen lägstanivå, inte att jämföra SE och US mot varandra.
    """
    parts = []
    if net_change < -50:
        parts.append(
            f"Aktien är ner {abs(net_change):.0f}% över perioden. Låg efficiency "
            "ratio kan bero på att den faller i etapper snarare än oscillerar."
        )
    if turnover < 300_000:
        parts.append(
            f"Tunn omsättning ({turnover:,.0f} {currency}/dag) — risk att bli fylld "
            "just när någon säljer av ett skäl du inte känner till."
        )
    return " ".join(parts) if parts else None


def screen_all(lookback: int = 250, market: str = "se") -> dict:
    tickers = usable_tickers(market)
    if not tickers:
        return {"error": "Inga validerade tickers. Kör datauppdateringen först."}

    results = []
    for t in tickers:
        try:
            results.append(analyze(t, lookback, market))
        except Exception as e:
            logger.error("Analys misslyckades för %s: %s", t, e)

    candidates = [r for r in results if r.get("usable")]
    candidates.sort(key=lambda r: r["score"], reverse=True)
    rejected = [r for r in results if not r.get("usable")]

    return {"candidates": candidates, "rejected": rejected,
            "screened": len(results)}
