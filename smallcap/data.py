"""
Hämtar dagliga kurser från Yahoo Finance.

Svenska aktier har suffixet .ST — till exempel ENEA.ST. Amerikanska
aktier har inget suffix — till exempel AAPL.

VIKTIG BEGRÄNSNING: Yahoos täckning av First North och de minsta
listorna är ojämn. Vissa bolag saknas helt, andra har luckor. Koden
rapporterar därför exakt vilka tickers som fungerade, så att du kan
bygga universum utifrån vad som faktiskt går att hämta. Samma gäller
för de mest illikvida amerikanska small caps.

VAD VI INTE FÅR: orderboksdata. Den finns inte gratis för svenska
småbolag eller amerikanska small caps. Det får en direkt konsekvens
för hur fills simuleras — se paper.py.
"""
import logging
from datetime import datetime, timezone

from .store import connect, get_bars
from .config import get_config

logger = logging.getLogger("data")


def read_universe(market: str = "se") -> list[str]:
    """
    Läser tickers från universe.txt (SE) eller universe_us.txt (US).

    En ticker per rad. Rader som börjar med # ignoreras, så du kan
    kommentera bort bolag utan att radera dem. För SE läggs .ST på
    automatiskt om det saknas. För US läggs inget suffix på.
    """
    cfg = get_config(market)
    if not cfg.universe_file.exists():
