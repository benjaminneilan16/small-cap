"""
Inställningar för båda marknaderna. Ändra här eller sätt miljövariabler.

Alla värden har fungerande standardvärden — du behöver inte konfigurera
något för att komma igång.

TVÅ MARKNADER: strategins princip (bred spread, spretig kurs, limit-
ordrar under marknaden) är marknadsoberoende — grundparametrarna delas.
Det som skiljer SE och US är sådant som faktiskt ÄR olika mellan
marknaderna: valuta, tickerformat, handelstider och courtagenivå.
Se MARKETS nedan för de marknadsspecifika värdena.
"""
import os
from pathlib import Path

ROOT = Path(__file__).parent.parent

# --- Kapital (delat startvärde, kan override:as per marknad) --------
STARTING_CAPITAL = float(os.getenv("STARTING_CAPITAL", "50000"))

# --- Strategi, från Folckes beskrivning — marknadsoberoende ----------
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

# --- Screener — marknadsoberoende -------------------------------------
# Minsta dagliga spann. Under detta finns inget att fånga efter courtage.
MIN_DAILY_RANGE_PCT = float(os.getenv("MIN_DAILY_RANGE_PCT", "3.0"))

# Efficiency ratio: LÅG är bra här. Över detta trendar aktien för
# tydligt och studsarna blir opålitliga.
MAX_EFFICIENCY_RATIO = float(os.getenv("MAX_EFFICIENCY_RATIO", "0.30"))

# --- Gap-flagga vid fyllnad (nytt) -------------------------------------
# Om en order fylls med ett större prisgap än detta jämfört med
# limitpriset (dagens LÅGA gick klart under, inte bara nätt och jämnt
# under), flaggas det i rapporten. Stort gap kan betyda att du blev
# fylld på väg ner i ett ras, inte vid en sund studs.
FILL_GAP_WARNING_PCT = float(os.getenv("FILL_GAP_WARNING_PCT", "5.0"))

# --- Telegram (valfritt, delas mellan marknaderna) ---------------------
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")


# --- Marknadsspecifika inställningar ------------------------------------
MARKETS = {
    "se": {
        "label": "Sverige",
        "currency": "kr",
        "ticker_suffix": ".ST",
        # Rader utan suffix i universe-filen tolkas som denna marknad
        "universe_file": ROOT / "universe.txt",
        "report_file": "latest.md",
        # Nordnet Mini: 0,25%, minst 1 kr
        "commission_pct": float(os.getenv("SE_COMMISSION_PCT", "0.25")),
        "commission_min": float(os.getenv("SE_COMMISSION_MIN", "1.0")),
        # Under detta blir du kanske aldrig fylld (kronor/dag)
        "min_daily_turnover": float(os.getenv("SE_MIN_DAILY_TURNOVER", "100000")),
        # Stockholmsbörsen: 09:00–17:30 CET/CEST
        "market_close_utc": "15:30",   # sommartid (CEST = UTC+2)
        "market_close_utc_winter": "16:30",  # vintertid (CET = UTC+1)
        "market_open_utc": "07:00",    # sommartid
        "market_open_utc_winter": "08:00",
    },
    "us": {
        "label": "USA",
        "currency": "$",
        "ticker_suffix": "",  # inget suffix — AAPL, inte AAPL.US
        "universe_file": ROOT / "universe_us.txt",
        "report_file": "latest_us.md",
        # Typiskt courtage hos en nordisk mäklare för US-aktier
        "commission_pct": float(os.getenv("US_COMMISSION_PCT", "0.15")),
        "commission_min": float(os.getenv("US_COMMISSION_MIN", "1.5")),  # USD
        # Under detta blir du kanske aldrig fylld (dollar/dag)
        "min_daily_turnover": float(os.getenv("US_MIN_DAILY_TURNOVER", "50000")),
        # Nasdaq/NYSE: 09:30–16:00 ET
        "market_close_utc": "20:00",   # sommartid (EDT = UTC-4)
        "market_close_utc_winter": "21:00",  # vintertid (EST = UTC-5)
        "market_open_utc": "13:30",    # sommartid
        "market_open_utc_winter": "14:30",
    },
}


class MarketConfig:
    """
    Ett konfigurationsobjekt för en given marknad.

    Används istället för modulnivå-konstanter så att SE och US kan
    hållas isär i samma process (t.ex. i tester) utan att en import
    "fryser" fel marknads inställningar.
    """

    def __init__(self, market: str):
        if market not in MARKETS:
            raise ValueError(f"okänd marknad '{market}', förväntade en av {list(MARKETS)}")
        self.market = market
        m = MARKETS[market]
        self.label = m["label"]
        self.currency = m["currency"]
        self.ticker_suffix = m["ticker_suffix"]
        self.universe_file = m["universe_file"]
        self.report_file = m["report_file"]
        self.commission_pct = m["commission_pct"]
        self.commission_min = m["commission_min"]
        self.min_daily_turnover = m["min_daily_turnover"]
        self.market_close_utc = m["market_close_utc"]
        self.market_close_utc_winter = m["market_close_utc_winter"]
        self.market_open_utc = m["market_open_utc"]
        self.market_open_utc_winter = m["market_open_utc_winter"]

        # Delade, marknadsoberoende värden — samma för alla marknader
        self.starting_capital = STARTING_CAPITAL
        self.target_profit_pct = TARGET_PROFIT_PCT
        self.position_size_pct = POSITION_SIZE_PCT
        self.max_exposure_pct = MAX_EXPOSURE_PCT
        self.max_open_orders = MAX_OPEN_ORDERS
        self.buy_below_pct = BUY_BELOW_PCT
        self.order_ttl_days = ORDER_TTL_DAYS
        self.stop_loss_pct = STOP_LOSS_PCT
        self.min_daily_range_pct = MIN_DAILY_RANGE_PCT
        self.max_efficiency_ratio = MAX_EFFICIENCY_RATIO
        self.fill_gap_warning_pct = FILL_GAP_WARNING_PCT

    @property
    def reports_dir(self) -> Path:
        return ROOT / "reports"


def get_config(market: str = "se") -> MarketConfig:
    return MarketConfig(market)


# --- Bakåtkompatibla modulnivå-värden (default = SE) --------------------
# Vissa delar av koden (och ev. egna script du skrivit) kan referera
# config.UNIVERSE_FILE eller config.REPORTS_DIR direkt. De pekar mot
# SE-marknaden som standard, precis som innan denna ändring.
UNIVERSE_FILE = MARKETS["se"]["universe_file"]
REPORTS_DIR = ROOT / "reports"
COMMISSION_PCT = MARKETS["se"]["commission_pct"]
COMMISSION_MIN_SEK = MARKETS["se"]["commission_min"]
MIN_DAILY_TURNOVER_SEK = MARKETS["se"]["min_daily_turnover"]
