#!/usr/bin/env python3
"""
Intradagskoll — drar tillbaka ordrar som fallit kraftigt sedan de lades.

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
    withdrawn = result["withdrawn"]

    if not withdrawn:
        log.info("Inga ordrar drogs tillbaka.")
    else:
        for w in withdrawn:
            log.info("  DROG TILLBAKA %s (limit %.2f, sett så lågt som %.2f, "
                     "-%.1f%%)", w["ticker"], w["limit_price"], w["lowest_seen"],
                     w["drop_pct"])

        lines = [f"⚡ Intradagskoll — {cfg.label}",
                 f"{len(withdrawn)} order(rar) drogs tillbaka pga kraftigt fall:"]
        for w in withdrawn:
            lines.append(f"  {w['ticker']}: -{w['drop_pct']:.1f}% sedan ordern lades")
        report.telegram("\n".join(lines))

    log.info("Städade %d gamla intradagsrader.", result["pruned_rows"])
    log.info("Klart.")


if __name__ == "__main__":
    main()
