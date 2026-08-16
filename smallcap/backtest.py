"""
Backtest -- spelar upp historiken dag for dag.

VARFOR: utan detta skulle du behova vanta manader pa att fa veta om
strategin overhuvudtaget fungerar. Med tva ars historik far du ett
forsta svar pa nagra sekunder.

VARFOR DET AR TROVARDIGT HAR, till skillnad fran de flesta backtest:

  Samma kod. Fill-logiken, exit-reglerna och courtaget ar exakt samma
  funktioner som paper.py anvander live.

  Ingen lookahead. Loopen ger strategin bara staplar fram till och med
  dagens datum. Screenern kan aldrig se framtida kurser.

  Konservativ fyllnad. Priset maste ga IGENOM limitnivan, inte nudda
  den. Rundtur samma dag ar omojlig.

VAD DET FORTFARANDE INTE KAN FANGA:

  Om DIN order faktiskt hade blivit fylld. Vi vet att priset var dar,
  inte att det fanns en motpart for just dig.

  Overlevnadsbias. Universum bestar av bolag som finns idag. Bolag som
  avnoterats eller gatt i konkurs saknas -- och det ar precis de som
  hade skadat strategin mest.

Las alltsa resultatet som ett OVRE TAK, inte som en prognos.

MARKNADSPARAMETER: samma backtest-motor anvands for SE och US -- bara
databasen och konfigurationen som lases av byts ut.
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
    Spelar upp historiken. Returnerar resultat med samma matt som live.
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

    with connect(market) as c:
        row = c.execute("SELECT MIN(date) a, MAX(date) b FROM bars").fetchone()
    first, last = row["a"], row["b"]
    if not first:
        return {"error": "Ingen kursdata"}

    eval_start = start_date or first
    eval_end = end_date or last

    with connect(market) as c:
        all_days = [r["date"] for r in c.execute(
            "SELECT DISTINCT date FROM bars WHERE date <= ? ORDER BY date",
            (eval_end,)).fetchall()]

    try:
        eval_start_idx = next(i for i, d in enumerate(all_days) if d >= eval_start)
    except StopIteration:
        return {"error": f"Inget data fran och med {eval_start}"}

    warmup = 120
    if eval_start_idx < warmup:
        return {"error": f"For lite historik fore {eval_start} "
                         f"({eval_start_idx} dagar, behover >{warmup} for uppvarmning)"}

    days = all_days

    real_get_bars = paper.get_bars
    real_screener_get_bars = screener.get_bars

    equity_curve = []
    trades_by_day = []

    try:
        for i, today in enumerate(days[eval_start_idx:], start=eval_start_idx):
            def limited(ticker, limit=400, _d=today, _m=market, market=None):
                return _bars_until(ticker, _d, limit, _m)

            paper.get_bars = limited
            screener.get_bars = limited

            paper.datetime = _FakeDatetime(today)

            actions = paper.process(market)
            screen = screener.screen_all(market=market, skip_volume_spike=True)
            placed = []
            if "error" not in screen:
                placed = paper.place_orders(screen.get("candidates", []), market)

            if actions["fills"] or actions["exits"]:
                trades_by_day.append({
                    "date": today,
                    "fills": len(actions["fills"]),
                    "exits": actions["exits"],
                })

            if i % 10 == 0 or i == len(days) - 1:
                pf = paper.portfolio(market)
                equity_curve.append({"date": today, "total": pf["total"]})
    finally:
        paper.get_bars = real_get_bars
        screener.get_bars = real_screener_get_bars
        import datetime as _dt
        paper.datetime = _dt.datetime

    perf = paper.performance(market)

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
            "Vi vet att priset nadde limitnivan, inte att just din order fylldes.",
            "Universum bestar av bolag som finns idag -- avnoterade saknas "
            "(overlevnadsbias).",
            "Las resultatet som ett ovre tak, inte som en prognos.",
        ],
    }
    return perf


class _FakeDatetime:
    """Later paper.py tro att det ar en viss dag, for TTL-berakningar."""
    def __init__(self, day: str):
        self._day = date.fromisoformat(day)

    def now(self, tz=None):
        return self

    def date(self):
        return self._day


def _buy_and_hold(tickers: list[str], start: str, end: str,
                  capital: float, market: str = "se") -> float | None:
    """Lika mycket i varje bolag fran start till slut. Referensen."""
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
    total += per * (len(tickers) - counted)
    return round((total - capital) / capital * 100, 2)


# --- Walk-forward-parametrisering -----------------------------------------
#
# VARFOR: fasta trosklar (MIN_DAILY_RANGE_PCT, MAX_EFFICIENCY_RATIO osv)
# ar en gissning som gjordes en gang och sen aldrig ifragasattes.
#
# METODEN: dela historiken i rullande fonster. For varje fonster, testa
# flera parameterkombinationer pa perioden FORE fonstret ("in-sample"),
# valj den kombination som presterade bast dar, och mat sedan HUR DEN
# KOMBINATIONEN presterar pa fonstret EFTER ("out-of-sample").
#
# VIKTIGT ATT VARA ARLIG OM: aven out-of-sample-resultat pa en enda
# walk-forward-korning ar bara EN observation av hur metoden presterar.

PARAM_GRID = {
    "min_daily_range_pct": [2.5, 4.0],
    "max_efficiency_ratio": [0.25, 0.35],
    "target_profit_pct": [6.0, 9.0],
}
# 8 kombinationer (2x2x2), inte 27 (3x3x3). VARFOR MINDRE AR RATT HAR:
# varje kombination kor en fullstandig backtest.run() en gang per
# fonster. Med verkliga marknadsstorlekar (300+ bolag i USA) blev 27
# kombinationer opraktiskt langsamt aven efter att databasanslutningar
# atervands (se store.py). Ett smalare grid ger ett snabbare, om an
# grovre, svar. Skicka ett eget grid-argument till walk_forward() om
# du vill testa fler kombinationer nar du har tid att vanta langre.


def _param_combinations(grid: dict) -> list[dict]:
    """Alla kombinationer av parametervarden i grid (kartesisk produkt)."""
    import itertools
    keys = list(grid.keys())
    values = list(grid.values())
    return [dict(zip(keys, combo)) for combo in itertools.product(*values)]


def _run_with_params(params: dict, start_date: str, end_date: str,
                     capital: float, market: str) -> dict:
    """
    Kor backtest.run() med temporart overskrivna parametrar.
    """
    market_settings = config.MARKETS[market]
    original = {k: market_settings.get(k) for k in params}
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
    Testar parameterkombinationer pa rullande fonster.
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
        return {"error": f"For lite historik for walk-forward "
                         f"(behover minst {warmup + window_days*2} dagar, "
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
        return {"error": "Inga fullstandiga fonster i historiken"}

    logger.info("Walk-forward: %d fonster, %d parameterkombinationer per fonster",
               len(windows), len(combos))

    results = []
    for w_i, (is_start, is_end, oos_start, oos_end) in enumerate(windows, 1):
        logger.info("Fonster %d/%d: in-sample %s-%s, out-of-sample %s-%s",
                   w_i, len(windows), is_start, is_end, oos_start, oos_end)

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

        oos_result = _run_with_params(best_combo, oos_start, oos_end, capital, market)
        oos_return = (oos_result["portfolio"]["return_pct"]
                     if "error" not in oos_result else None)

        results.append({
            "window": w_i,
            "in_sample_period": f"{is_start} - {is_end}",
            "out_of_sample_period": f"{oos_start} - {oos_end}",
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
            "Ut-av-provresultat ar den arligaste indikationen pa om "
            "parametervalet generaliserar -- men det ar fortfarande bara "
            "en handfull fonster, inte en garanti. Stor spridning mellan "
            "fonster tyder pa att strategin ar kanslig for marknadsklimat, "
            "inte att en ratt parameteruppsattning hittats."
        ),
    }
