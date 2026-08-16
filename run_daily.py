#!/usr/bin/env python3
"""
Daglig korning.

Detta ar hela programmet. Det kors en gang per dag via GitHub Actions
efter respektive marknads stangning, gor sitt jobb, och avslutas.

TVA MARKNADER: samma script hanterar bade Sverige och USA via
--market-flaggan.

Ordningen spelar roll:
  1. Hamta kurser      -- annars fattas beslut pa gammal data
  2. Kolla fills       -- innan nya ordrar laggs
  3. Screena           -- vilka bolag passar just nu
  4. Lagg ordrar       -- for de basta kandidaterna
  5. Skriv rapport     -- sa du kan lasa resultatet pa GitHub

Kor manuellt med:
    python run_daily.py                    (svenska marknaden, standard)
    python run_daily.py --market us         (amerikanska marknaden)
    python run_daily.py --reset             (nollstall kontot)
    python run_daily.py --no-orders         (uppdatera utan nya ordrar)
    python run_daily.py --backtest          (spela upp historiken)
    python run_daily.py --walk-forward      (testa parameterkombinationer)
"""
import argparse
import logging
import sys

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("run")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--market", choices=["se", "us"], default="se",
                    help="vilken marknad som ska koras (standard: se)")
    ap.add_argument("--reset", action="store_true", help="nollstall papperskontot")
    ap.add_argument("--no-orders", action="store_true", help="lagg inga nya ordrar")
    ap.add_argument("--skip-fetch", action="store_true", help="hoppa over datahamtning")
    ap.add_argument("--backtest", action="store_true",
                    help="spela upp historiken istallet for att kora live")
    ap.add_argument("--walk-forward", action="store_true",
                    help="testa parameterkombinationer pa rullande fonster")
    ap.add_argument("--window-days", type=int, default=90,
                    help="fonsterstorlek i dagar for walk-forward (standard: 90)")
    args = ap.parse_args()

    if args.walk_forward:
        run_walk_forward(args.market, args.skip_fetch, args.window_days)
        return

    if args.backtest:
        run_backtest(args.market, args.skip_fetch)
        return

    from smallcap import store, data, screener, paper, report, config

    market = args.market
    cfg = config.get_config(market)
    log.info("Marknad: %s", cfg.label)

    store.init(market)

    if args.reset:
        store.reset_account(cfg.starting_capital, market)
        log.info("Kontot nollstallt till %.0f %s", cfg.starting_capital, cfg.currency)

    store.init_account(cfg.starting_capital, market)

    # --- 1. Hamta kurser ---
    if not args.skip_fetch:
        log.info("Hamtar kurser...")
        result = data.update_all(market=market)
        if "error" in result:
            log.error(result["error"])
            sys.exit(1)
        log.info("%d bolag med anvandbar data, %d utan",
                 result["usable"], result["unusable"])
        if result["unusable"]:
            for f in result["failed"][:10]:
                log.warning("  %s: %s", f["ticker"], f.get("error") or "for lite data")

    if not data.usable_tickers(market):
        log.error("Inga bolag med anvandbar data. Kolla %s och att tickers "
                  "har ratt format.", cfg.universe_file.name)
        sys.exit(1)

    # --- 2. Kolla fills FORE nya ordrar ---
    log.info("Kollar ordrar och positioner...")
    actions = paper.process(market)
    for f in actions["fills"]:
        gap_note = f"  (gap {f['gap_pct']:.1f}%)" if f.get("gap_warning") else ""
        log.info("  KOPT %s @ %.2f (mal %.2f)%s", f["ticker"], f["price"],
                 f["target"], gap_note)
    for e in actions["exits"]:
        log.info("  SALT %s @ %.2f -- %s, %+.0f %s efter %d dagar",
                 e["ticker"], e["price"], e["reason"], e["pnl"], cfg.currency, e["days"])

    # --- 3. Screena ---
    log.info("Screenar...")
    screen = screener.screen_all(market=market)
    if "error" in screen:
        log.error(screen["error"])
        sys.exit(1)
    log.info("%d av %d bolag passar kriterierna",
             len(screen["candidates"]), screen["screened"])

    # --- 4. Lagg ordrar ---
    placed = []
    if not args.no_orders:
        placed = paper.place_orders(screen["candidates"], market)
        log.info("Lade %d nya kopordrar", len(placed))
    actions["placed"] = placed

    # --- 5. Rapport ---
    perf = paper.performance(market)
    text = report.build(screen, actions, perf, market)
    report.write(text, market)
    report.export_csv(market)

    pf = perf["portfolio"]
    log.info("Portfolj: %.0f %s (%+.2f %%), exponering %.0f %%, kapital i vila %.0f %%, "
             "%d oppna positioner", pf["total"], cfg.currency, pf["return_pct"],
             pf["exposure_pct"], pf["idle_capital_pct"], pf["open_positions"])

    from datetime import datetime, timezone
    with store.connect(market) as c:
        c.execute(
            "INSERT INTO runs (run_at, kind, fills, exits, cancels, orders_placed, "
            "total_value) VALUES (?, 'daily', ?, ?, ?, ?, ?)",
            (datetime.now(timezone.utc).isoformat(), len(actions["fills"]),
             len(actions["exits"]), len(actions["cancels"]), len(placed), pf["total"]),
        )

    # --- Telegram: skickas ALLTID, inte bara vid fills/exits ---
    lines = [f"Kvallskorning -- {cfg.label}",
             f"{pf['total']:,.0f} {cfg.currency} ({pf['return_pct']:+.2f} %)",
             f"Exponering {pf['exposure_pct']:.0f} %, kapital i vila "
             f"{pf['idle_capital_pct']:.0f} %, {pf['open_positions']} oppna positioner"]
    if actions["exits"] or actions["fills"] or placed:
        lines.append("")
    for e in actions["exits"]:
        lines.append(f"{'+' if e['pnl'] >= 0 else ''}{e['pnl']:.0f} {cfg.currency}  "
                     f"{e['ticker']}  {e['reason']}")
    for f in actions["fills"]:
        gap_note = " [STORT GAP]" if f.get("gap_warning") else ""
        lines.append(f"KOPT {f['ticker']} @ {f['price']:.2f}{gap_note}")
    if placed and not (actions["exits"] or actions["fills"]):
        lines.append(f"{len(placed)} nya kopordrar lagda")
    if not (actions["exits"] or actions["fills"] or placed):
        lines.append("Inget hande idag -- normalt, de flesta ordrar ligger och vantar.")
    report.telegram("\n".join(lines))

    # Checkpointar WAL och stanger anslutningen INNAN workflow-filens
    # git-steg committar databasen -- annars kan den senaste datan sitta
    # kvar i en -wal-sidofil som aldrig nar git. Se store.close_all().
    store.close_all()

    log.info("Klart.")


def run_backtest(market: str = "se", skip_fetch: bool = False):
    """
    Spelar upp historiken dag for dag med samma logik som live.

    KORS MOT EN ISOLERAD BACKTEST-DATABAS (market + "_bt"), ALDRIG mot
    den riktiga paper-portfoljen -- backtest.run() anropar
    reset_account() som en del av simuleringen.
    """
    from smallcap import store, data, backtest, config

    cfg = config.get_config(market)
    bt_market = f"{market}_bt"

    store.init(market)
    if not skip_fetch:
        log.info("Hamtar historik...")
        result = data.update_all(market=market)
        if "error" in result:
            log.error(result["error"])
            sys.exit(1)
        log.info("%d bolag med data", result["usable"])

    log.info("Kopierar prisdata till isolerad backtest-databas...")
    store.init(bt_market)
    with store.connect(market) as src, store.connect(bt_market) as dst:
        dst.execute("DELETE FROM universe")
        dst.execute("DELETE FROM bars")
        for row in src.execute("SELECT * FROM universe"):
            cols = row.keys()
            placeholders = ",".join("?" * len(cols))
            dst.execute(f"INSERT INTO universe ({','.join(cols)}) VALUES ({placeholders})",
                       tuple(row))
        for row in src.execute("SELECT * FROM bars"):
            cols = row.keys()
            placeholders = ",".join("?" * len(cols))
            dst.execute(f"INSERT INTO bars ({','.join(cols)}) VALUES ({placeholders})",
                       tuple(row))

    log.info("Kor backtest (%s)...", cfg.label)
    r = backtest.run(capital=cfg.starting_capital, market=bt_market)
    if "error" in r:
        log.error(r["error"])
        sys.exit(1)

    bt = r["backtest"]
    pf = r["portfolio"]
    cur = cfg.currency

    print()
    print("=" * 62)
    print(f"  BACKTEST -- {cfg.label}  {bt['start']} till {bt['end']}")
    print(f"  {bt['trading_days']} handelsdagar, {bt['tickers']} bolag")
    print("=" * 62)
    print()
    print(f"  Slutvarde            {pf['total']:>12,.0f} {cur}")
    print(f"  Avkastning           {pf['return_pct']:>11.2f} %")
    if bt["buy_and_hold_pct"] is not None:
        print(f"  Buy & hold           {bt['buy_and_hold_pct']:>11.2f} %")
        print(f"  Slar referensen      {'JA' if bt['beats_buy_and_hold'] else 'NEJ':>12}")
    print()
    print(f"  Avslutade affarer    {r['closed_trades']:>12}")
    if r["closed_trades"]:
        print(f"  Vinstandel           {r['win_rate_pct']:>11.1f} %")
        print(f"  Snittvinst           {r['avg_win'] or 0:>11.0f} {cur}")
        print(f"  Snittforlust         {r['avg_loss'] or 0:>11.0f} {cur}")
        if r.get("profit_factor"):
            print(f"  Profit factor        {r['profit_factor']:>12}")
        print(f"  Snitt halltid        {r['avg_days_held'] or 0:>11.0f} dagar")
        print(f"  Fyllnadsgrad         {r['fill_rate_pct'] or 0:>11.1f} %")
        print(f"  Genomsn. max motgang {r['avg_mae_pct'] or 0:>11.1f} %")
        if r.get("avg_gap_pct") is not None:
            print(f"  Genomsn. gap         {r['avg_gap_pct']:>11.1f} %")
        print(f"  Exit-orsaker         {r['exit_reasons']}")
    print()
    print("  FORBEHALL:")
    for c in bt["caveats"]:
        print(f"    - {c}")
    print()
    if r.get("note"):
        print(f"  {r['note']}")
    print()

    store.close_all()


def run_walk_forward(market: str = "se", skip_fetch: bool = False,
                     window_days: int = 90):
    """
    Testar parameterkombinationer pa rullande fonster, se backtest.py.

    KORS MOT EN ISOLERAD BACKTEST-DATABAS (market + "_bt"), ALDRIG mot
    den riktiga paper-portfoljen.
    """
    from smallcap import store, data, backtest, config

    cfg = config.get_config(market)
    bt_market = f"{market}_bt"

    store.init(market)
    if not skip_fetch:
        log.info("Hamtar historik...")
        result = data.update_all(market=market)
        if "error" in result:
            log.error(result["error"])
            return
        log.info("%d bolag med data", result["usable"])

    log.info("Kopierar prisdata till isolerad backtest-databas...")
    store.init(bt_market)
    with store.connect(market) as src, store.connect(bt_market) as dst:
        dst.execute("DELETE FROM universe")
        dst.execute("DELETE FROM bars")
        for row in src.execute("SELECT * FROM universe"):
            cols = row.keys()
            placeholders = ",".join("?" * len(cols))
            dst.execute(f"INSERT INTO universe ({','.join(cols)}) VALUES ({placeholders})",
                       tuple(row))
        for row in src.execute("SELECT * FROM bars"):
            cols = row.keys()
            placeholders = ",".join("?" * len(cols))
            dst.execute(f"INSERT INTO bars ({','.join(cols)}) VALUES ({placeholders})",
                       tuple(row))

    log.info("Kor walk-forward (%s), fonster om %d dagar...", cfg.label, window_days)
    r = backtest.walk_forward(window_days=window_days, market=bt_market)
    if "error" in r:
        log.error(r["error"])
        return

    print()
    print("=" * 70)
    print(f"  WALK-FORWARD -- {cfg.label}")
    print("=" * 70)
    print()
    for w in r["windows"]:
        if "error" in w:
            print(f"  Fonster {w['window']}: {w['error']}")
            continue
        print(f"  Fonster {w['window']}: {w['in_sample_period']} -> "
             f"{w['out_of_sample_period']}")
        print(f"    Basta parametrar (in-sample):  {w['best_params']}")
        print(f"    In-sample avkastning:          {w['in_sample_return_pct']:+.2f} %")
        oos = w['out_of_sample_return_pct']
        print(f"    Out-of-sample avkastning:      "
             f"{oos:+.2f} %" if oos is not None else "    Out-of-sample avkastning:      (fel)")
        print()

    if r.get("avg_out_of_sample_return_pct") is not None:
        print(f"  Snitt out-of-sample-avkastning: {r['avg_out_of_sample_return_pct']:+.2f} %")
    print()
    print(f"  {r['note']}")
    print()

    store.close_all()


if __name__ == "__main__":
    main()
