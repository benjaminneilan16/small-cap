"""
Inställningar. Ändra här eller sätt miljövariabler.

Alla värden har fungerande standardvärden — du behöver inte konfigurera
något för att komma igång.
"""
import os
from pathlib import Path

ROOT = Path(__file__).parent.parent

# --- Kapital ---------------------------------------------------------
STARTING_CAPITAL = float(os.getenv("STARTING_CAPITAL", "50000"))

# --- Strategi, från Folckes beskrivning ------------------------------
# "Grundtanken är att jag ska utnyttja en stor spread, tänk 5-10 procent"
TARGET_PROFIT_PCT = float(os.getenv("TARGET_PROFIT_PCT", "7.0"))

# "Det handlar om små, små positioner i varje order"
POSITION_SIZE_PCT = float(os.getenv("POSITION_SIZE_PCT", "2.0"))

# "Jag kanske har max 30 procent i faktiska trades"
MAX_EXPOSURE_PCT = float(os.getenv("MAX_EXPOSURE_PCT", "30.0"))

# "Det kan vara uppåt hundra ordrar"
MAX_OPEN_ORDERS = int(os.getenv("MAX_OPEN_ORDERS", "100"))

# Hur långt under senaste kurs köpordern läggs.
# "Jag håller mig där köparna ligger" — alltså under marknaden.
BUY_BELOW_PCT = float(os.getenv("BUY_BELOW_PCT", "4.0"))

# Order som inte fyllts inom denna tid tas bort och läggs om
ORDER_TTL_DAYS = int(os.getenv("ORDER_TTL_DAYS", "10"))

# Stop loss. Artikeln nämner ingen, men utan skydd blir en fallande
# aktie en position man sitter i för alltid — och det är precis så
# adverse selection gör ont.
STOP_LOSS_PCT = float(os.getenv("STOP_LOSS_PCT", "-15.0"))

# --- Courtage: Nordnet Mini (0,25%, minst 1 kr) ----------------------
COMMISSION_PCT = float(os.getenv("COMMISSION_PCT", "0.25"))
COMMISSION_MIN_SEK = float(os.getenv("COMMISSION_MIN_SEK", "1.0"))

# --- Screener --------------------------------------------------------
# Minsta dagliga spann. Under detta finns inget att fånga efter courtage.
MIN_DAILY_RANGE_PCT = float(os.getenv("MIN_DAILY_RANGE_PCT", "3.0"))

# Efficiency ratio: LÅG är bra här. Över detta trendar aktien för
# tydligt och studsarna blir opålitliga.
MAX_EFFICIENCY_RATIO = float(os.getenv("MAX_EFFICIENCY_RATIO", "0.30"))

# Minsta omsättning per dag. Under detta blir du kanske aldrig fylld.
MIN_DAILY_TURNOVER_SEK = float(os.getenv("MIN_DAILY_TURNOVER_SEK", "100000"))

# --- Telegram (valfritt) ---------------------------------------------
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

# --- Filer -----------------------------------------------------------
UNIVERSE_FILE = ROOT / "universe.txt"
REPORTS_DIR = ROOT / "reports"
