#!/usr/bin/env python3
"""
Morgonkoll — körs runt öppning, INTE en full daglig körning.

VAD DEN GÖR: hämtar senaste kursdata, kollar om någon öppen köporder
fylldes i öppningsauktionen, och skickar ALLTID en kort Telegram-status
— även när inget hänt. Tanken är att statusmeddelandet i sig är
värdefullt: det bekräftar att systemet lever och kört som det ska,
inte bara när något dramatiskt inträffat.

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

    from smallcap.store import connect
    with connect(market) as c:
        checked = c.execute(
            "SELECT COUNT(*) n FROM orders WHERE status = 'open' AND side = 'buy'"
        ).fetchone()["n"]

    fills = []
    if checked == 0:
        log.info("Inga öppna köpordrar att kolla.")
    else:
        # Hämta färsk data — bara för tickers med öppna ordrar, för att
        # hålla morgonkollen snabb. Detta skiljer den från run_daily.py
        # som uppdaterar hela universum.
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
        else:
            # VIKTIGT: skriv om CSV-filerna när något faktiskt fyllts.
            # Utan detta blir positions.csv/orders.csv kvar i sitt gamla
            # skick tills nästa kvällskörning (run_daily.py) — appen
            # (som läser CSV, inte databasen direkt) skulle då visa
            # "inga positioner" trots att en riktig fyllnad skett för
            # länge sen. latest.md/latest_us.md skrivs INTE om här
            # (det är fortfarande kvällskörningens ansvar att bygga
            # den fulla rapporten) — bara de rådata-filer appen
            # behöver för att visa korrekta positioner/ordrar direkt.
            report.export_csv(market)
            log.info("Skrev om positions.csv/orders.csv efter fyllnad(er).")

    # Portföljvärdet skrivs ALLTID om, oavsett om något fylldes eller
    # inte — annars kan avkastningssiffran i appen bli inaktuell även
    # på dagar utan fyllnader (t.ex. om en position stängdes till
    # stop/mål under natten och portföljvärdet därför förändrats utan
    # någon ny KÖP-fyllnad denna morgon).
    report.write_portfolio_json(market)

    # Skicka status ALLTID — det är själva poängen med en morgonkoll.
    # Tystnad går inte att skilja från "inget hänt" och "något är
    # trasigt", så vi skickar hellre en kort bekräftelse varje gång.
    pf = paper.portfolio(market)
    status = {"checked": checked, "fills": fills, "portfolio": pf}
    summary = report.build_morning_summary(status, market)
    report.telegram(summary)

    # Checkpointar WAL och stänger anslutningen INNAN workflow-filens
    # git-steg committar databasen/CSV-filerna — se run_daily.py för
    # samma resonemang.
    store.close_all()

    log.info("Klart.")


if __name__ == "__main__":
    main()
