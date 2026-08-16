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

MARKNADSPARAMETER: samma backtest-motor används för SE och US — bara
databasen och konfigurationen som läses av bytes ut.
"""
import logging
from datetime import date

from .store import connect, get_bars
from . import config, screener, paper

logger = logging.getLogger("backtest")


def _bars_until(ticker: str, until: str, limit: int = 400, market: str = "se") -> list[dict]:
    with connect(market) as c:
        rows = c.execute(
            "SELECT date, open, high, low, close, volume FROM bars "
            "WHERE ticker = ? AND date <= ? ORDER BY date DESC LIMIT ?",
            (ticker, until, limit),
        ).fetchall()
    return [dict(r) for r in reversed(rows)]


def run(start_date: str = None, end_date: str = None,
        capital: float = None, market: str = "se") -> dict:
    """
    Spelar upp historiken. Returnerar resultat med samma mått som live.

    Simuleringen ersätter datakällan men behåller all annan logik —
    samma fill-regler, samma exit-regler, samma courtage.
    """
    from .store import reset_account, init
    from .data import usable_tickers

    cfg = config.get_config(market)
    capital = capital or cfg.starting_capital
    init(market)
    reset_account(capital, market)

    tickers = usable_tickers(market)
    if not tickers:
        return {"error": "Inga bolag med data"}

    # Hitta gemensamt datumintervall
    with connect(market) as c:
        row = c.execute("SELECT MIN(date) a, MAX(date) b FROM bars").fetchone()
    first, last = row["a"], row["b"]
    if not first:
        return {"error": "Ingen kursdata"}

    eval_start = start_date or first
    eval_end = end_date or last

    # ALLA handelsdagar i databasen, inte bara evalueringsperioden — vi
    # behöver kunna se dagar FÖRE eval_start för uppvärmning (screenern
    # kräver historik för att bedöma ett bolag). Bara dagarna FRÅN OCH
    # MED eval_start faktiskt SIMULERAS och mäts; dagarna före används
    # enbart som kontext att titta bakåt på, precis som i skarpt läge.
    with connect(market) as c:
        all_days = [r["date"] for r in c.execute(
            "SELECT DISTINCT date FROM bars WHERE date <= ? ORDER BY date",
            (eval_end,)).fetchall()]

    # Hitta var evalueringsperioden faktiskt börjar i den fullständiga listan
    try:
        eval_start_idx = next(i for i, d in enumerate(all_days) if d >= eval_start)
    except StopIteration:
        return {"error": f"Inget data från och med {eval_start}"}

    warmup = 120
    if eval_start_idx < warmup:
        return {"error": f"För lite historik före {eval_start} "
                         f"({eval_start_idx} dagar, behöver >{warmup} för uppvärmning)"}

    days = all_days  # simuleringsloopen nedan använder eval_start_idx som startpunkt

    # Monkey-patcha datakällan så att strategin bara ser dagar <= today.
    # Detta är hela lookahead-skyddet: samma kod, men den kan bara nå
    # data som fanns vid beslutstillfället.
    real_get_bars = paper.get_bars
    real_screener_get_bars = screener.get_bars

    equity_curve = []
    trades_by_day = []

    try:
        for i, today in enumerate(days[eval_start_idx:], start=eval_start_idx):
            def limited(ticker, limit=400, _d=today, _m=market, market=None):
                # market-kwarg ignoreras avsiktligt här: under backtest
                # patchar vi bara aktuell marknads get_bars, så anropet
                # kommer alltid från rätt kontext.
                return _bars_until(ticker, _d, limit, _m)

            paper.get_bars = limited
            screener.get_bars = limited

            # Simulera "idag" för TTL-beräkningar
            paper.datetime = _FakeDatetime(today)

            actions = paper.process(market)
            screen = screener.screen_all(market=market)
            placed = []
            if "error" not in screen:
                placed = paper.place_orders(screen.get("candidates", []), market)

            if actions["fills"] or actions["exits"]:
                trades_by_day.append({
                    "date": today,
                    "fills": len(actions["fills"]),
                    "exits": actions["exits"],
                })

            # Kapitalkurva varje tionde dag för att hålla den läsbar
            if i % 10 == 0 or i == len(days) - 1:
                pf = paper.portfolio(market)
                equity_curve.append({"date": today, "total": pf["total"]})
    finally:
        paper.get_bars = real_get_bars
        screener.get_bars = real_screener_get_bars
        import datetime as _dt
        paper.datetime = _dt.datetime

    perf = paper.performance(market)

    # Buy & hold som jämförelse: lika mycket i varje bolag från start
    bh = _buy_and_hold(tickers, days[eval_start_idx], days[-1], capital, market)

    perf["backtest"] = {
        "start": days[eval_start_idx],
        "end": days[-1],
        "trading_days": len(days) - eval_start_idx,
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
                  capital: float, market: str = "se") -> float | None:
    """Lika mycket i varje bolag från start till slut. Referensen."""
    per = capital / len(tickers)
    total = 0.0
    counted = 0
    for t in tickers:
        bars = _bars_until(t, end, market=market)
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


# --- Walk-forward-parametrisering -----------------------------------------
#
# VARFÖR: fasta trösklar (MIN_DAILY_RANGE_PCT, MAX_EFFICIENCY_RATIO osv)
# är en gissning som gjordes en gång och sen aldrig ifrågasattes. Vad som
# fungerade för sex månader sen fungerar inte nödvändigtvis nu — bolagens
# volatilitetsprofil, marknadsklimat och likviditet förändras.
#
# METODEN: dela historiken i rullande fönster. För varje fönster, testa
# flera parameterkombinationer på perioden FÖRE fönstret ("in-sample"),
# välj den kombination som presterade bäst där, och mät sedan HUR DEN
# KOMBINATIONEN presterar på fönstret EFTER ("out-of-sample" — det
# fönstret har den aldrig "sett"). Det är skillnaden mellan att bara
# leta efter parametrar som råkar passa hela historiken perfekt
# (overfitting, värdelöst för framtiden) och att testa om en metod för
# att VÄLJA parametrar generaliserar till okänd framtida data.
#
# VIKTIGT ATT VARA ÄRLIG OM: även out-of-sample-resultat på en enda
# walk-forward-körning är bara EN observation av hur metoden presterar.
# Det säger något, men inte allt — samma försiktighet som gäller för
# hela backtestet (se modulens docstring) gäller här också.

PARAM_GRID = {
    "min_daily_range_pct": [2.0, 3.0, 4.0],
    "max_efficiency_ratio": [0.20, 0.30, 0.40],
    "target_profit_pct": [5.0, 7.0, 10.0],
}


def _param_combinations(grid: dict) -> list[dict]:
    """Alla kombinationer av parametervärden i grid (kartesisk produkt)."""
    import itertools
    keys = list(grid.keys())
    values = list(grid.values())
    return [dict(zip(keys, combo)) for combo in itertools.product(*values)]


def _run_with_params(params: dict, start_date: str, end_date: str,
                     capital: float, market: str) -> dict:
    """
    Kör backtest.run() med temporärt överskrivna parametrar.

    Överskriver config.MARKETS[market] direkt (samma dict som
    MarketConfig läser från vid varje get_config()-anrop), så att
    ALL kod som läser konfiguration under körningen — screener,
    paper, allt — automatiskt använder testparametrarna utan att
    behöva skickas explicit genom hela anropskedjan.
    """
    market_settings = config.MARKETS[market]
    original = {k: market_settings.get(k) for k in params}
    # target_profit_pct m.fl. är marknadsoberoende moduld-nivå-konstanter,
    # inte MARKETS-nycklar — hantera separat.
    module_level_keys = {"target_profit_pct": "TARGET_PROFIT_PCT",
                          "position_size_pct": "POSITION_SIZE_PCT",
                          "buy_below_pct": "BUY_BELOW_PCT",
                          "stop_loss_pct": "STOP_LOSS_PCT"}
    original_module_values = {}

    try:
        for key, value in params.items():
            if key in module_level_keys:
                attr = module_level_keys[key]
                original_module_values[attr] = getattr(config, attr)
                setattr(config, attr, value)
            else:
                market_settings[key] = value

        return run(start_date=start_date, end_date=end_date,
                  capital=capital, market=market)
    finally:
        for key, value in original.items():
            if key not in module_level_keys:
                market_settings[key] = value
        for attr, value in original_module_values.items():
            setattr(config, attr, value)


def walk_forward(window_days: int = 90, grid: dict | None = None,
                 capital: float | None = None, market: str = "se") -> dict:
    """
    Testar parameterkombinationer på rullande fönster.

    För varje fönster: hitta bästa parametrar på föregående period
    (in-sample), applicera dem oförändrade på nästa period
    (out-of-sample), mät faktisk avkastning där.

    Detta är kostsamt (kör hela backtestet en gång per parameter-
    kombination per fönster), så window_days styr hur många fönster
    som testas — större fönster = färre, snabbare körningar.
    """
    from .store import connect as _connect

    cfg = config.get_config(market)
    capital = capital or cfg.starting_capital
    grid = grid or PARAM_GRID
    combos = _param_combinations(grid)

    with _connect(market) as c:
        row = c.execute("SELECT MIN(date) a, MAX(date) b FROM bars").fetchone()
    first, last = row["a"], row["b"]
    if not first:
        return {"error": "Ingen kursdata"}

    with _connect(market) as c:
        all_days = [r["date"] for r in c.execute(
            "SELECT DISTINCT date FROM bars ORDER BY date").fetchall()]

    warmup = 120
    if len(all_days) < warmup + window_days * 2:
        return {"error": f"För lite historik för walk-forward "
                         f"(behöver minst {warmup + window_days*2} dagar, "
                         f"har {len(all_days)})"}

    windows = []
    i = warmup
    while i + window_days * 2 <= len(all_days):
        in_sample_start = all_days[i]
        in_sample_end = all_days[i + window_days - 1]
        out_start = all_days[i + window_days]
        out_end = all_days[min(i + window_days * 2 - 1, len(all_days) - 1)]
        windows.append((in_sample_start, in_sample_end, out_start, out_end))
        i += window_days

    if not windows:
        return {"error": "Inga fullständiga fönster i historiken"}

    logger.info("Walk-forward: %d fönster, %d parameterkombinationer per fönster",
               len(windows), len(combos))

    results = []
    for w_i, (is_start, is_end, oos_start, oos_end) in enumerate(windows, 1):
        logger.info("Fönster %d/%d: in-sample %s–%s, out-of-sample %s–%s",
                   w_i, len(windows), is_start, is_end, oos_start, oos_end)

        # In-sample: testa alla kombinationer, hitta bäst
        best_combo = None
        best_return = None
        for combo in combos:
            r = _run_with_params(combo, is_start, is_end, capital, market)
            if "error" in r:
                continue
            ret = r["portfolio"]["return_pct"]
            if best_return is None or ret > best_return:
                best_return = ret
                best_combo = combo

        if best_combo is None:
            results.append({"window": w_i, "error": "ingen kombination gav resultat"})
            continue

        # Out-of-sample: applicera BÄSTA in-sample-kombinationen, oförändrad
        oos_result = _run_with_params(best_combo, oos_start, oos_end, capital, market)
        oos_return = (oos_result["portfolio"]["return_pct"]
                     if "error" not in oos_result else None)

        results.append({
            "window": w_i,
            "in_sample_period": f"{is_start} – {is_end}",
            "out_of_sample_period": f"{oos_start} – {oos_end}",
            "best_params": best_combo,
            "in_sample_return_pct": round(best_return, 2),
            "out_of_sample_return_pct": (round(oos_return, 2)
                                         if oos_return is not None else None),
        })

    oos_returns = [r["out_of_sample_return_pct"] for r in results
                  if r.get("out_of_sample_return_pct") is not None]

    return {
        "windows": results,
        "avg_out_of_sample_return_pct": (round(sum(oos_returns) / len(oos_returns), 2)
                                         if oos_returns else None),
        "note": (
            "Ut-av-provresultat är den ärligaste indikationen på om "
            "parametervalet generaliserar — men det är fortfarande bara "
            "en handfull fönster, inte en garanti. Stor spridning mellan "
            "fönster tyder på att strategin är känslig för marknadsklimat, "
            "inte att en 'rätt' parameteruppsättning hittats."
        ),
    }
