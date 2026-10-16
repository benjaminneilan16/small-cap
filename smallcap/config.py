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

# Nya filter (se screener.analyze). Standardvardena stangar av dem sa att
# beteendet ar oforandrat om en marknad inte sjalv sa att de ska anvandas.
MIN_PRICE = float(os.getenv("MIN_PRICE", "0"))
MAX_DECLINE_PCT = float(os.getenv("MAX_DECLINE_PCT", "100"))   # 100 = av
REQUIRE_UPTREND = os.getenv("REQUIRE_UPTREND", "0") == "1"
MAX_DAILY_RANGE_PCT = float(os.getenv("MAX_DAILY_RANGE_PCT", "1000"))  # 1000 = av

# Walk-forward skriver hit tillfalliga parametervarden. MarketConfig
# laser dem FORST, sedan marknadens egna "params", sist globala standard.
# (Tidigare skrevs min_daily_range_pct och max_efficiency_ratio till
# MARKETS-dictionaryn, som aldrig lastes -- de parametrarna hade ingen
# effekt alls i walk-forward.)
PARAM_OVERRIDES: dict = {}

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
        "params": {},
    },
    "us": {
        "label": "USA Blue chips",
        "strategy_version": "bluechip-1",
        "params": {
            # Blue chips har tata spreadar -- Marja-logiken (stora
            # spreadar, stora dagsrorelser) finns inte. Har gar vi
            # istallet efter korta dippar i STARKA bolag:
            # kop nagra procent under kurs, ta vinst snabbt, hall
            # forlusten liten, handla bara i uppatgaende trend.
            "target_profit_pct": 3.0,
            "stop_loss_pct": -5.0,
            "buy_below_pct": 2.0,
            "order_ttl_days": 5,
            "min_daily_range_pct": 1.2,
            "max_efficiency_ratio": 0.35,
            "early_warning_pct": -4.0,
            "require_uptrend": True,
            "max_decline_pct": 100.0,
            "min_price": 5.0,
            "max_daily_range_pct": 8.0,
            "position_size_pct": 3.0,
            "max_exposure_pct": 45.0,
            "max_open_orders": 40,
        },
        "currency": "$",
        "ticker_suffix": "",
        "universe_file": ROOT / "universe_us.txt",
        "report_file": "latest_us.md",
        "commission_pct": float(os.getenv("US_COMMISSION_PCT", "0.15")),
        "commission_min": float(os.getenv("US_COMMISSION_MIN", "1.5")),
        "min_daily_turnover": float(os.getenv("US_MIN_DAILY_TURNOVER", "20000000")),
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

        self.strategy_version = m.get("strategy_version", "smallcap-1")
        self.starting_capital = STARTING_CAPITAL

        defaults = {
            "target_profit_pct": TARGET_PROFIT_PCT,
            "position_size_pct": POSITION_SIZE_PCT,
            "max_exposure_pct": MAX_EXPOSURE_PCT,
            "max_open_orders": MAX_OPEN_ORDERS,
            "buy_below_pct": BUY_BELOW_PCT,
            "order_ttl_days": ORDER_TTL_DAYS,
            "stop_loss_pct": STOP_LOSS_PCT,
            "min_daily_range_pct": MIN_DAILY_RANGE_PCT,
            "max_efficiency_ratio": MAX_EFFICIENCY_RATIO,
            "fill_gap_warning_pct": FILL_GAP_WARNING_PCT,
            "intraday_interval": INTRADAY_INTERVAL,
            "intraday_period": INTRADAY_PERIOD,
            "intraday_pullback_pct": INTRADAY_PULLBACK_PCT,
            "intraday_adjust_pct": INTRADAY_ADJUST_PCT,
            "intraday_adjust_below_pct": INTRADAY_ADJUST_BELOW_PCT,
            "intraday_max_adjustments": INTRADAY_MAX_ADJUSTMENTS,
            "volume_spike_multiplier": VOLUME_SPIKE_MULTIPLIER,
            "volume_spike_lookback_days": VOLUME_SPIKE_LOOKBACK_DAYS,
            "early_warning_days": EARLY_WARNING_DAYS,
            "early_warning_pct": EARLY_WARNING_PCT,
            "min_price": MIN_PRICE,
            "max_decline_pct": MAX_DECLINE_PCT,
            "require_uptrend": REQUIRE_UPTREND,
            "max_daily_range_pct": MAX_DAILY_RANGE_PCT,
        }
        market_params = m.get("params", {})
        for key, default in defaults.items():
            if key in PARAM_OVERRIDES:
                value = PARAM_OVERRIDES[key]
            elif key in market_params:
                value = market_params[key]
            else:
                value = default
            setattr(self, key, value)

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
