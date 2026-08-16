"""
Installningar for bada marknaderna. Andra har eller satt miljovariabler.

Alla varden har fungerande standardvarden -- du behover inte konfigurera
nagot for att komma igang.
"""
import os
from pathlib import Path

ROOT = Path(__file__).parent.parent

STARTING_CAPITAL = float(os.getenv("STARTING_CAPITAL", "50000"))
TARGET_PROFIT_PCT = float(os.getenv("TARGET_PROFIT_PCT", "7.0"))
POSITION_SIZE_PCT = float(os.getenv("POSITION_SIZE_PCT", "2.0"))
MAX_EXPOSURE_PCT = float(os.getenv("MAX_EXPOSURE_PCT", "30.0"))
MAX_OPEN_ORDERS = int(os.getenv("MAX_OPEN_ORDERS", "100"))
BUY_BELOW_PCT = float(os.getenv("BUY_BELOW_PCT", "4.0"))
ORDER_TTL_DAYS = int(os.getenv("ORDER_TTL_DAYS", "10"))
STOP_LOSS_PCT = float(os.getenv("STOP_LOSS_PCT", "-15.0"))
MIN_DAILY_RANGE_PCT = float(os.getenv("MIN_DAILY_RANGE_PCT", "3.0"))
MAX_EFFICIENCY_RATIO = float(os.getenv("MAX_EFFICIENCY_RATIO", "0.30"))
FILL_GAP_WARNING_PCT = float(os.getenv("FILL_GAP_WARNING_PCT", "5.0"))

INTRADAY_INTERVAL = os.getenv("INTRADAY_INTERVAL", "5m")
INTRADAY_PERIOD = os.getenv("INTRADAY_PERIOD", "5d")

# Hur mycket priset far falla INTRADAG under en liggande limitorder
# innan vi drar tillbaka den.
INTRADAY_PULLBACK_PCT = float(os.getenv("INTRADAY_PULLBACK_PCT", "8.0"))

# Vid vilket intradagsfall vi JUSTERAR limitpriset nedat istallet for
# att bara lata ordern ligga still. Maste vara lagre an
# INTRADAY_PULLBACK_PCT -- det skapar tre lagen: under denna troskel
# gors inget (normal dagsrorelse), mellan denna och pullback justeras
# ordern for att folja kursen ner, over pullback dras den tillbaka
# helt. Se intraday.adjust_orders().
INTRADAY_ADJUST_PCT = float(os.getenv("INTRADAY_ADJUST_PCT", "4.0"))

# Hur langt UNDER det nya, lagre priset den justerade ordern laggs.
INTRADAY_ADJUST_BELOW_PCT = float(os.getenv("INTRADAY_ADJUST_BELOW_PCT", "2.0"))

# Max antal ganger en enskild order far justeras innan den istallet
# dras tillbaka. Utan detta tak skulle en aktie i ihallande, jamn
# nedgang kunna fa ordern justerad om och om igen hela vagen ner --
# vilket i praktiken vore detsamma som att jaga kursen nedat.
INTRADAY_MAX_ADJUSTMENTS = int(os.getenv("INTRADAY_MAX_ADJUSTMENTS", "2"))

VOLUME_SPIKE_MULTIPLIER = float(os.getenv("VOLUME_SPIKE_MULTIPLIER", "3.0"))
VOLUME_SPIKE_LOOKBACK_DAYS = int(os.getenv("VOLUME_SPIKE_LOOKBACK_DAYS", "20"))

EARLY_WARNING_DAYS = int(os.getenv("EARLY_WARNING_DAYS", "2"))
EARLY_WARNING_PCT = float(os.getenv("EARLY_WARNING_PCT", "-8.0"))

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")


MARKETS = {
    "se": {
        "label": "Sverige",
        "currency": "kr",
        "ticker_suffix": ".ST",
        "universe_file": ROOT / "universe.txt",
        "report_file": "latest.md",
        "commission_pct": float(os.getenv("SE_COMMISSION_PCT", "0.25")),
        "commission_min": float(os.getenv("SE_COMMISSION_MIN", "1.0")),
        "min_daily_turnover": float(os.getenv("SE_MIN_DAILY_TURNOVER", "100000")),
        "market_close_utc": "15:30",
        "market_close_utc_winter": "16:30",
        "market_open_utc": "07:00",
        "market_open_utc_winter": "08:00",
    },
    "us": {
        "label": "USA",
        "currency": "$",
        "ticker_suffix": "",
        "universe_file": ROOT / "universe_us.txt",
        "report_file": "latest_us.md",
        "commission_pct": float(os.getenv("US_COMMISSION_PCT", "0.15")),
        "commission_min": float(os.getenv("US_COMMISSION_MIN", "1.5")),
        "min_daily_turnover": float(os.getenv("US_MIN_DAILY_TURNOVER", "50000")),
        "market_close_utc": "20:00",
        "market_close_utc_winter": "21:00",
        "market_open_utc": "13:30",
        "market_open_utc_winter": "14:30",
    },
}


class MarketConfig:
    """
    Ett konfigurationsobjekt for en given marknad.
    """

    def __init__(self, market: str):
        settings_key = market.removesuffix("_bt")
        if settings_key not in MARKETS:
            raise ValueError(f"okand marknad '{market}', forvantade en av "
                            f"{list(MARKETS)} (valfritt med _bt-suffix)")
        self.market = market
        m = MARKETS[settings_key]
        self.label = m["label"] + (" (backtest)" if market != settings_key else "")
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
        self.intraday_interval = INTRADAY_INTERVAL
        self.intraday_period = INTRADAY_PERIOD
        self.intraday_pullback_pct = INTRADAY_PULLBACK_PCT
        self.intraday_adjust_pct = INTRADAY_ADJUST_PCT
        self.intraday_adjust_below_pct = INTRADAY_ADJUST_BELOW_PCT
        self.intraday_max_adjustments = INTRADAY_MAX_ADJUSTMENTS
        self.volume_spike_multiplier = VOLUME_SPIKE_MULTIPLIER
        self.volume_spike_lookback_days = VOLUME_SPIKE_LOOKBACK_DAYS
        self.early_warning_days = EARLY_WARNING_DAYS
        self.early_warning_pct = EARLY_WARNING_PCT

    @property
    def reports_dir(self) -> Path:
        return ROOT / "reports"


def get_config(market: str = "se") -> MarketConfig:
    return MarketConfig(market)


UNIVERSE_FILE = MARKETS["se"]["universe_file"]
REPORTS_DIR = ROOT / "reports"
COMMISSION_PCT = MARKETS["se"]["commission_pct"]
COMMISSION_MIN_SEK = MARKETS["se"]["commission_min"]
MIN_DAILY_TURNOVER_SEK = MARKETS["se"]["min_daily_turnover"]
