#!/usr/bin/env python3
"""
Morgonkoll — körs runt öppning, INTE en full daglig körning.

VAD DEN GÖR: hämtar senaste kursdata, kollar om någon öppen köporder
fylldes i öppningsauktionen, och skickar ALLTID en kort Telegram-status
— även när inget hänt.

VAD DEN INTE GÖR: lägger inga nya ordrar, ändrar ingen strategi, skriver
inte om huvudrapporten (latest.md).

Kör manuellt med:
    python run_morning.py                 (svenska marknaden, standard)
    python run_morning.py --market us      (amerikanska marknaden)
"""
import argparse
import logging
import sys

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("morning")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--market", choices=["se", "us"], default="se",
                    help="vilken marknad som ska kollas (standard: se)")
    ap.add_argument("--skip-fetch", action="store_true",
                    help="hoppa över datahämtning (använd redan sparad data)")
    args = ap.parse_args()

    from smallcap import store, data, paper, report, config

    market = args.market
    cfg = config.get_config(market)
    log.info("Morgonkoll — %s", cfg.label)

    store.init(market)
    store.init_account(cfg.starting_capital, market)

    from smallcap.store import connect
    with connect(market) as c:
        checked = c.execute(
            "SELECT COUNT(*) n FROM orders WHERE status = 'open' AND side = 'buy'"
        ).fetchone()["n"]

    fills = []
    if checked == 0:
        log.info("Inga öppna köpordrar att kolla.")
    else:
        if not args.skip_fetch:
            log.info("Hämtar senaste kurser för %d bolag med öppna ordrar...", checked)
            with connect(market) as c:
                tickers = [r["ticker"] for r in c.execute(
                    "SELECT DISTINCT ticker FROM orders WHERE status = 'open' AND side = 'buy'"
                ).fetchall()]
            for t in tickers:
                data.fetch(t, period="5d", market=market)

        actions = paper.process(market)
        fills = actions["fills"]

        for f in fills:
            gap_note = "  ⚠️ STORT GAP" if f.get("gap_warning") else ""
            log.info("  FYLLD %s @ %.2f%s", f["ticker"], f["price"], gap_note)

        if not fills:
            log.info("Inget nytt sen igår — %d ordrar ligger fortfarande och väntar.", checked)
        else:
            # VIKTIGT: skriv om CSV-filerna när något faktiskt fyllts.
            # Utan detta blir positions.csv/orders.csv kvar i sitt gamla
            # skick tills nästa kvällskörning — appen (som läser CSV,
            # inte databasen direkt) skulle då visa "inga positioner"
            # trots att en riktig fyllnad skett för länge sen.
            report.export_csv(market)
            log.info("Skrev om positions.csv/orders.csv efter fyllnad(er).")

    pf = paper.portfolio(market)
    status = {"checked": checked, "fills": fills, "portfolio": pf}
    summary = report.build_morning_summary(status, market)
    report.telegram(summary)

    # Checkpointar WAL och stänger anslutningen INNAN workflow-filens
    # git-steg committar databasen/CSV-filerna.
    store.close_all()

    log.info("Klart.")


if __name__ == "__main__":
    main()
