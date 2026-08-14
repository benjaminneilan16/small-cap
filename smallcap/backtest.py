"""
Backtest — spelar upp historiken dag för dag.

VARFÖR: utan detta skulle du behöva vänta månader på att få veta om
strategin överhuvudtaget fungerar. Med två års historik får du ett
första svar på några sekunder.

VARFÖR DET ÄR TROVÄRDIGT HÄR, till skillnad från de flesta backtest:

  Samma kod. Fill-logiken, exit-reglerna och courtaget är exakt samma
  funktioner som paper.py använder live. Bygger man en separat
  "backtest-version" testar man något annat än det som faktiskt körs.

  Ingen lookahead. Loopen ger strategin bara staplar fram till och med
  dagens datum. Screenern kan aldrig se framtida kurser.

  Konservativ fyllnad. Priset måste gå IGENOM limitnivån, inte nudda
  den. Rundtur samma dag är omöjlig.

VAD DET FORTFARANDE INTE KAN FÅNGA:

  Om DIN order faktiskt hade blivit fylld. Vi vet att priset var där,
  inte att det fanns en motpart för just dig. I ett bolag som omsätter
  100 000 kr om dagen är det en verklig osäkerhet.

  Överlevnadsbias. Universum består av bolag som finns idag. Bolag som
  avnoterats eller gått i konkurs saknas — och det är precis de som
  hade skadat strategin mest.

Läs alltså resultatet som ett OVRE TAK, inte som en prognos.
"""
import logging
from datetime import date, timedelta

from .store import connect, get_bars
from . import config, screener, paper

logger = logging.getLogger("backtest")


def _bars_until(ticker: str, until: str, limit: int = 400) -> list[dict]:
    with connect() as c:
        rows = c.execute(
            "SELECT date, open, high, low, close, volume FROM bars "
            "WHERE ticker = ? AND date <= ? ORDER BY date DESC LIMIT ?",
            (ticker, until, limit),
        ).fetchall()
    return [dict(r) for r in reversed(rows)]


def run(start_date: str = None, end_date: str = None,
        capital: float = None) -> dict:
    """
    Spelar upp historiken. Returnerar resultat med samma mått som live.

    Simuleringen ersätter datakällan men behåller all annan logik —
    samma fill-regler, samma exit-regler, samma courtage.
    """
    from .store import reset_account, init
    from .data import usable_tickers

    capital = capital or config.STARTING_CAPITAL
    init()
    reset_account(capital)

    tickers = usable_tickers()
    if not tickers:
        return {"error": "Inga bolag med data"}

    # Hitta gemensamt datumintervall
    with connect() as c:
        row = c.execute("SELECT MIN(date) a, MAX(date) b FROM bars").fetchone()
    first, last = row["a"], row["b"]
    if not first:
        return {"error": "Ingen kursdata"}

    start = start_date or first
    end = end_date or last

    # Alla handelsdagar i intervallet
    with connect() as c:
        days = [r["date"] for r in c.execute(
            "SELECT DISTINCT date FROM bars WHERE date >= ? AND date <= ? "
            "ORDER BY date", (start, end)).fetchall()]

    # Behöver historik innan vi kan screena
    warmup = 120
    if len(days) <= warmup:
        return {"error": f"För lite historik ({len(days)} dagar, behöver >{warmup})"}

    # Monkey-patcha datakällan så att strategin bara ser dagar <= today.
    # Detta är hela lookahead-skyddet: samma kod, men den kan bara nå
    # data som fanns vid beslutstillfället.
    real_get_bars = paper.get_bars
    real_screener_get_bars = screener.get_bars

    equity_curve = []
    trades_by_day = []

    try:
        for i, today in enumerate(days[warmup:], start=warmup):
            def limited(ticker, limit=400, _d=today):
                return _bars_until(ticker, _d, limit)

            paper.get_bars = limited
            screener.get_bars = limited

            # Simulera "idag" för TTL-beräkningar
            paper.datetime = _FakeDatetime(today)

            actions = paper.process()
            screen = screener.screen_all()
            placed = []
            if "error" not in screen:
                placed = paper.place_orders(screen.get("candidates", []))

            if actions["fills"] or actions["exits"]:
                trades_by_day.append({
                    "date": today,
                    "fills": len(actions["fills"]),
                    "exits": actions["exits"],
                })

            # Kapitalkurva varje tionde dag för att hålla den läsbar
            if i % 10 == 0 or i == len(days) - 1:
                pf = paper.portfolio()
                equity_curve.append({"date": today, "total": pf["total"]})
    finally:
        paper.get_bars = real_get_bars
        screener.get_bars = real_screener_get_bars
        import datetime as _dt
        paper.datetime = _dt.datetime

    perf = paper.performance()

    # Buy & hold som jämförelse: lika mycket i varje bolag från start
    bh = _buy_and_hold(tickers, days[warmup], days[-1], capital)

    perf["backtest"] = {
        "start": days[warmup],
        "end": days[-1],
        "trading_days": len(days) - warmup,
        "tickers": len(tickers),
        "equity_curve": equity_curve,
        "buy_and_hold_pct": bh,
        "beats_buy_and_hold": (perf["portfolio"]["return_pct"] > bh
                               if bh is not None else None),
        "caveats": [
            "Vi vet att priset nådde limitnivån, inte att just din order fylldes.",
            "Universum består av bolag som finns idag — avnoterade saknas "
            "(överlevnadsbias).",
            "Läs resultatet som ett övre tak, inte som en prognos.",
        ],
    }
    return perf


class _FakeDatetime:
    """Låter paper.py tro att det är en viss dag, för TTL-beräkningar."""
    def __init__(self, day: str):
        self._day = date.fromisoformat(day)

    def now(self, tz=None):
        return self

    def date(self):
        return self._day


def _buy_and_hold(tickers: list[str], start: str, end: str,
                  capital: float) -> float | None:
    """Lika mycket i varje bolag från start till slut. Referensen."""
    per = capital / len(tickers)
    total = 0.0
    counted = 0
    for t in tickers:
        bars = _bars_until(t, end)
        entry = next((b for b in bars if b["date"] >= start), None)
        if not entry or not bars:
            continue
        shares = per / float(entry["close"])
        total += shares * float(bars[-1]["close"])
        counted += 1
    if not counted:
        return None
    # Bolag utan data behåller sin kontantdel
    total += per * (len(tickers) - counted)
    return round((total - capital) / capital * 100, 2)
