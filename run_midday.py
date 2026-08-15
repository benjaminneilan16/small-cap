#!/usr/bin/env python3
"""
Mitt på dagen-koll — en ren "lever"-signal, ingen datahämtning.

VAD DEN GÖR: skickar ett kort Telegram-meddelande med portföljens
senast kända värde (från gårdagens stängning) och antal öppna
positioner/ordrar. Inget mer.

VARFÖR INGEN NY DATA HÄMTAS: Yahoo Finance ger dagliga staplar som
inte är kompletta förrän efter stängning (se data.py och paper.py för
varför resten av systemet är byggt kring det). Mitt på handelsdagen
finns därför ingen tillförlitlig ny information att hämta eller agera
på — att låtsas annat vore att bryta mot den konservativa principen
resten av koden bygger på.

VARFÖR DEN ÄR VÄRDEFULL ÄNDÅ: det här är en ren "botten lever"-signal.
Om du inte hör något mitt på dagen OCH inget kvällsmeddelande kommer
senare, vet du att något är fel med körningarna — inte bara att
marknaden var lugn. Tre tysta punkter om dagen (morgon/mitt på
dagen/kväll) ger dig den säkerheten utan att kräva att du loggar in
på GitHub för att kolla Actions-fliken.

Kör manuellt med:
    python run_midday.py                 (svenska marknaden, standard)
    python run_midday.py --market us      (amerikanska marknaden)
"""
import argparse
import logging

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("midday")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--market", choices=["se", "us"], default="se",
                    help="vilken marknad som ska kollas (standard: se)")
    args = ap.parse_args()

    from smallcap import store, report, config

    market = args.market
    cfg = config.get_config(market)
    log.info("Mitt på dagen-koll — %s", cfg.label)

    store.init(market)
    store.init_account(cfg.starting_capital, market)

    summary = report.build_midday_summary(market)
    sent = report.telegram(summary)

    if sent:
        log.info("Statusmeddelande skickat.")
    else:
        log.info("Telegram inte konfigurerat (eller misslyckades) — "
                 "hoppar över utan fel.")

    log.info("Klart.")


if __name__ == "__main__":
    main()
