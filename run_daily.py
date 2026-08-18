#!/usr/bin/env python3
"""
Daglig körning.

Detta är hela programmet. Det körs en gång per dag via GitHub Actions
efter respektive marknads stängning, gör sitt jobb, och avslutas. Ingen
server som står och kostar mellan körningarna.

TVÅ MARKNADER: samma script hanterar både Sverige och USA via
--market-flaggan. De körs som separata GitHub Actions-jobb på olika
scheman (svensk resp. amerikansk stängningstid), och skriver till
separata databaser och rapporter — se README för detaljer.

Ordningen spelar roll:
  1. Hämta kurser      — annars fattas beslut på gammal data
  2. Kolla fills       — innan nya ordrar läggs, så exponeringen stämmer
  3. Screena           — vilka bolag passar just nu
  4. Lägg ordrar       — för de bästa kandidaterna
  5. Skriv rapport     — så du kan läsa resultatet på GitHub

Kör manuellt med:
    python run_daily.py                    (svenska marknaden, standard)
    python run_daily.py --market us         (amerikanska marknaden)
    python run_daily.py --reset             (nollställ kontot)
    python run_daily.py --no-orders         (uppdatera utan att lägga nya ordrar)
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
                    help="vilken marknad som ska köras (standard: se)")
    ap.add_argument("--reset", action="store_true", help="nollställ papperskontot")
    ap.add_argument("--no-orders", action="store_true", help="lägg inga nya ordrar")
    ap.add_argument("--skip-fetch", action="store_true", help="hoppa över datahämtning")
    ap.add_argument("--backtest", action="store_true",
                    help="spela upp historiken istället för att köra live")
    ap.add_argument("--walk-forward", action="store_true",
                    help="testa parameterkombinationer på rullande fönster")
    ap.add_argument("--window-days", type=int, default=90,
                    help="fönsterstorlek i dagar för walk-forward (standard: 90)")
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
        log.info("Kontot nollställt till %.0f %s", cfg.starting_capital, cfg.currency)

    store.init_account(cfg.starting_capital, market)

    # --- 1. Hämta kurser ---
    if not args.skip_fetch:
        log.info("Hämtar kurser...")
        result = data.update_all(market=market)
        if "error" in result:
            log.error(result["error"])
            sys.exit(1)
        log.info("%d bolag med användbar data, %d utan",
                 result["usable"], result["unusable"])
        if result["unusable"]:
            for f in result["failed"][:10]:
                log.warning("  %s: %s", f["ticker"], f.get("error") or "för lite data")

    if not data.usable_tickers(market):
        log.error("Inga bolag med användbar data. Kolla %s och att tickers "
                  "har rätt format.", cfg.universe_file.name)
        sys.exit(1)

    # --- 2. Kolla fills FÖRE nya ordrar ---
    log.info("Kollar ordrar och positioner...")
    actions = paper.process(market)
    for f in actions["fills"]:
        gap_note = f"  (gap {f['gap_pct']:.1f}%)" if f.get("gap_warning") else ""
        log.info("  KÖPT %s @ %.2f (mål %.2f)%s", f["ticker"], f["price"],
                 f["target"], gap_note)
    for e in actions["exits"]:
        log.info("  SÅLT %s @ %.2f — %s, %+.0f %s efter %d dagar",
                 e["ticker"], e["price"], e["reason"], e["pnl"], cfg.currency, e["days"])

    # --- 3. Screena ---
    log.info("Screenar...")
    screen = screener.screen_all(market=market)
    if "error" in screen:
        log.error(screen["error"])
        sys.exit(1)
    log.info("%d av %d bolag passar kriterierna",
             len(screen["candidates"]), screen["screened"])

    # --- 4. Lägg ordrar ---
    placed = []
    if not args.no_orders:
        placed = paper.place_orders(screen["candidates"], market)
        log.info("Lade %d nya köpordrar", len(placed))
    actions["placed"] = placed

    # --- 5. Rapport ---
    perf = paper.performance(market)
    text = report.build(screen, actions, perf, market)
    report.write(text, market)
    report.export_csv(market)
    report.write_portfolio_json(market)

    pf = perf["portfolio"]
    log.info("Portfölj: %.0f %s (%+.2f %%), exponering %.0f %%, kapital i vila %.0f %%, "
             "%d öppna positioner", pf["total"], cfg.currency, pf["return_pct"],
             pf["exposure_pct"], pf["idle_capital_pct"], pf["open_positions"])

    # Loggar körningen så du kan se historiken
    from datetime import datetime, timezone
    with store.connect(market) as c:
        c.execute(
            "INSERT INTO runs (run_at, kind, fills, exits, cancels, orders_placed, "
            "total_value) VALUES (?, 'daily', ?, ?, ?, ?, ?)",
            (datetime.now(timezone.utc).isoformat(), len(actions["fills"]),
             len(actions["exits"]), len(actions["cancels"]), len(placed), pf["total"]),
        )

    # --- Telegram: skickas ALLTID, inte bara vid fills/exits ---
    lines = [f"🌙 Kvällskörning — {cfg.label}",
             f"{pf['total']:,.0f} {cfg.currency} ({pf['return_pct']:+.2f} %)",
             f"Exponering {pf['exposure_pct']:.0f} %, kapital i vila "
             f"{pf['idle_capital_pct']:.0f} %, {pf['open_positions']} öppna positioner"]
    if actions["exits"] or actions["fills"] or placed:
        lines.append("")
    for e in actions["exits"]:
        lines.append(f"{'+' if e['pnl'] >= 0 else ''}{e['pnl']:.0f} {cfg.currency}  "
                     f"{e['ticker']}  {e['reason']}")
    for f in actions["fills"]:
        gap_note = " ⚠️ stort gap" if f.get("gap_warning") else ""
        lines.append(f"KÖPT {f['ticker']} @ {f['price']:.2f}{gap_note}")
    if placed and not (actions["exits"] or actions["fills"]):
        lines.append(f"{len(placed)} nya köpordrar lagda")
    if not (actions["exits"] or actions["fills"] or placed):
        lines.append("Inget hände idag — normalt, de flesta ordrar ligger och väntar.")
    report.telegram("\n".join(lines))

    # Checkpointar WAL och stänger anslutningen INNAN workflow-filens
    # git-steg committar databasen — annars kan den senaste datan sitta
    # kvar i en -wal-sidofil som aldrig når git. Se store.close_all().
    store.close_all()

    log.info("Klart.")


def run_backtest(market: str = "se", skip_fetch: bool = False):
    """
    Spelar upp historiken dag för dag med samma logik som live.

    KÖRS MOT EN ISOLERAD BACKTEST-DATABAS (market + "_bt"), ALDRIG mot
    den riktiga paper-portföljen — se run_walk_forward() för samma
    resonemang. backtest.run() anropar reset_account() som en del av
    simuleringen, vilket annars skulle skriva över din riktiga
    portföljhistorik.
    """
    from smallcap import store, data, backtest, config

    cfg = config.get_config(market)
    bt_market = f"{market}_bt"

    store.init(market)
    if not skip_fetch:
        log.info("Hämtar historik...")
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

    log.info("Kör backtest (%s)...", cfg.label)
    r = backtest.run(capital=cfg.starting_capital, market=bt_market)
    if "error" in r:
        log.error(r["error"])
        sys.exit(1)

    bt = r["backtest"]
    pf = r["portfolio"]
    cur = cfg.currency

    print()
    print("=" * 62)
    print(f"  BACKTEST — {cfg.label}  {bt['start']} till {bt['end']}")
    print(f"  {bt['trading_days']} handelsdagar, {bt['tickers']} bolag")
    print("=" * 62)
    print()
    print(f"  Slutvärde            {pf['total']:>12,.0f} {cur}")
    print(f"  Avkastning           {pf['return_pct']:>11.2f} %")
    if bt["buy_and_hold_pct"] is not None:
        print(f"  Buy & hold           {bt['buy_and_hold_pct']:>11.2f} %")
        print(f"  Slår referensen      {'JA' if bt['beats_buy_and_hold'] else 'NEJ':>12}")
    print()
    print(f"  Avslutade affärer    {r['closed_trades']:>12}")
    if r["closed_trades"]:
        print(f"  Vinstandel           {r['win_rate_pct']:>11.1f} %")
        print(f"  Snittvinst           {r['avg_win'] or 0:>11.0f} {cur}")
        print(f"  Snittförlust         {r['avg_loss'] or 0:>11.0f} {cur}")
        if r.get("profit_factor"):
            print(f"  Profit factor        {r['profit_factor']:>12}")
        print(f"  Snitt hålltid        {r['avg_days_held'] or 0:>11.0f} dagar")
        print(f"  Fyllnadsgrad         {r['fill_rate_pct'] or 0:>11.1f} %")
        print(f"  Genomsn. max motgång {r['avg_mae_pct'] or 0:>11.1f} %")
        if r.get("avg_gap_pct") is not None:
            print(f"  Genomsn. gap         {r['avg_gap_pct']:>11.1f} %")
        print(f"  Exit-orsaker         {r['exit_reasons']}")
    print()
    print("  FÖRBEHÅLL:")
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
    Testar parameterkombinationer på rullande fönster, se backtest.py.

    KÖRS MOT EN ISOLERAD BACKTEST-DATABAS (market + "_bt"), ALDRIG mot
    den riktiga paper-portföljen. backtest.run() anropar reset_account()
    som en del av varje simulering — kördes det mot samma databas som
    den dagliga produktionskörningen använder skulle en walk-forward-
    analys skriva över din riktiga portföljhistorik. Se store.py för
    fullständigt resonemang.
    """
    from smallcap import store, data, backtest, config

    cfg = config.get_config(market)
    bt_market = f"{market}_bt"

    store.init(market)
    if not skip_fetch:
        log.info("Hämtar historik...")
        result = data.update_all(market=market)
        if "error" in result:
            log.error(result["error"])
            return
        log.info("%d bolag med data", result["usable"])

    # Kopiera prisdata (universe + bars) till den isolerade backtest-
    # databasen. Kontot/positionerna/ordrarna kopieras INTE — de
    # nollställs ändå av reset_account() i varje simulering.
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

    log.info("Kör walk-forward (%s), fönster om %d dagar...", cfg.label, window_days)
    r = backtest.walk_forward(window_days=window_days, market=bt_market)
    if "error" in r:
        log.error(r["error"])
        return

    print()
    print("=" * 70)
    print(f"  WALK-FORWARD — {cfg.label}")
    print("=" * 70)
    print()
    for w in r["windows"]:
        if "error" in w:
            print(f"  Fönster {w['window']}: {w['error']}")
            continue
        print(f"  Fönster {w['window']}: {w['in_sample_period']} → "
             f"{w['out_of_sample_period']}")
        print(f"    Bästa parametrar (in-sample):  {w['best_params']}")
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
