#!/usr/bin/env python3
"""
Intradagskoll — justerar ordrar som fallit måttligt, drar tillbaka
ordrar som fallit kraftigt sedan de lades.

Körs några gånger under handelsdagen (t.ex. varannan timme), separat
från morgonkoll/mitt på dagen/kvällskörning. Se smallcap/intraday.py
för det fullständiga resonemanget om varför detta behövs och vad det
inte kan ersätta.

Kör manuellt med:
    python run_intraday.py                 (svenska marknaden, standard)
    python run_intraday.py --market us      (amerikanska marknaden)
"""
import argparse
import logging

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("intraday_run")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--market", choices=["se", "us"], default="se",
                    help="vilken marknad som ska kollas (standard: se)")
    args = ap.parse_args()

    from smallcap import store, intraday, report, config

    market = args.market
    cfg = config.get_config(market)
    log.info("Intradagskoll — %s", cfg.label)

    store.init(market)
    store.init_account(cfg.starting_capital, market)

    result = intraday.run_intraday_check(market)
    adjusted = result["adjusted"]
    withdrawn = result["withdrawn"]

    if not adjusted:
        log.info("Inga ordrar justerade.")
    else:
        for a in adjusted:
            log.info("  JUSTERADE %s: %.2f -> %.2f (fallit %.1f%%, %d/%d)",
                     a["ticker"], a["old_limit"], a["new_limit"], a["drop_pct"],
                     a["adjustments_count"], cfg.intraday_max_adjustments)

    if not withdrawn:
        log.info("Inga ordrar drogs tillbaka.")
    else:
        for w in withdrawn:
            log.info("  DROG TILLBAKA %s (limit %.2f, sett så lågt som %.2f, "
                     "-%.1f%%)", w["ticker"], w["limit_price"], w["lowest_seen"],
                     w["drop_pct"])

    if adjusted or withdrawn:
        lines = [f"⚡ Intradagskoll — {cfg.label}"]
        if adjusted:
            lines.append(f"\n{len(adjusted)} order(rar) justerade (följer kursen ner):")
            for a in adjusted:
                lines.append(f"  {a['ticker']}: {a['old_limit']:.2f} → "
                            f"{a['new_limit']:.2f} ({a['drop_pct']:.1f}% fall)")
        if withdrawn:
            lines.append(f"\n{len(withdrawn)} order(rar) drogs tillbaka pga kraftigt fall:")
            for w in withdrawn:
                lines.append(f"  {w['ticker']}: -{w['drop_pct']:.1f}% sedan ordern lades")
        report.telegram("\n".join(lines))

        # Skriv om orders.csv så appen (som läser CSV, inte databasen
        # direkt) visar justerade limitpriser och tillbakadragna ordrar
        # direkt, utan att vänta till kvällskörningen.
        report.export_csv(market)
        report.write_portfolio_json(market)
        log.info("Skrev om orders.csv efter justering(ar)/tillbakadragning(ar).")

    log.info("Städade %d gamla intradagsrader.", result["pruned_rows"])

    # Checkpointar WAL innan workflow-filens git-steg committar
    # databasen — se run_daily.py för samma resonemang.
    store.close_all()

    log.info("Klart.")


if __name__ == "__main__":
    main()
