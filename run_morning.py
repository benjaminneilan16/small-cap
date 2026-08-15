#!/usr/bin/env python3
"""
Morgonkoll — körs runt öppning, INTE en full daglig körning.

VAD DEN GÖR: hämtar senaste kursdata och kollar om någon öppen köporder
fylldes i öppningsauktionen. Skickar en kort Telegram-status.

VAD DEN INTE GÖR: lägger inga nya ordrar, ändrar ingen strategi, skriver
inte om huvudrapporten. Den är en ren informationskoll — ett sätt att
veta om något hände innan du börjar din dag, utan att göra något som
den fulla körningen (run_daily.py) redan gör bättre efter stängning.

VARFÖR DET HÄR ÄR SÄRSKILT ANVÄNDBART VID ÖPPNING: öppningsauktionen kan
skapa prisrörelser som avviker kraftigt från föregående dags stängning —
övernattnyheter, andra marknaders utveckling. Om en limitorder ligger
kvar från kvällen innan och aktien gappar ner vid öppning, kan ordern
fyllas direkt till ett pris som redan speglar ny information. Det är
exakt den situationen gap-flaggan i paper.py är byggd för att fånga —
den här morgonkollen är bara det snabbaste sättet att FÅ syn på det.

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

    # Räkna öppna köpordrar INNAN vi kollar, för statusraden
    from smallcap.store import connect
    with connect(market) as c:
        checked = c.execute(
            "SELECT COUNT(*) n FROM orders WHERE status = 'open' AND side = 'buy'"
        ).fetchone()["n"]

    if checked == 0:
        log.info("Inga öppna köpordrar att kolla.")
        return

    # Hämta färsk data — bara för tickers med öppna ordrar, för att hålla
    # morgonkollen snabb. Detta skiljer den från run_daily.py som
    # uppdaterar hela universum.
    if not args.skip_fetch:
        log.info("Hämtar senaste kurser för %d bolag med öppna ordrar...", checked)
        with connect(market) as c:
            tickers = [r["ticker"] for r in c.execute(
                "SELECT DISTINCT ticker FROM orders WHERE status = 'open' AND side = 'buy'"
            ).fetchall()]
        for t in tickers:
            data.fetch(t, period="5d", market=market)

    # Kolla fills — ingen orderläggning, bara process()
    actions = paper.process(market)
    fills = actions["fills"]

    for f in fills:
        gap_note = "  ⚠️ STORT GAP" if f.get("gap_warning") else ""
        log.info("  FYLLD %s @ %.2f%s", f["ticker"], f["price"], gap_note)

    if not fills:
        log.info("Inget nytt sen igår — %d ordrar ligger fortfarande och väntar.", checked)

    status = {"checked": checked, "fills": fills}
    summary = report.build_morning_summary(status, market)
    report.telegram(summary)

    log.info("Klart.")


if __name__ == "__main__":
    main()
