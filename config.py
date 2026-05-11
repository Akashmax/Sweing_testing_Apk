"""Central configuration loaded from .env"""
import os
from pathlib import Path
from dotenv import load_dotenv

ROOT = Path(__file__).parent
load_dotenv(ROOT / ".env")


def _f(key, default):
    return float(os.getenv(key, default))


def _i(key, default):
    return int(os.getenv(key, default))


# WhatsApp
NOTIFIER = os.getenv("NOTIFIER", "console").lower()
CALLMEBOT_PHONE = os.getenv("CALLMEBOT_PHONE", "")
CALLMEBOT_APIKEY = os.getenv("CALLMEBOT_APIKEY", "")
TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID", "")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN", "")
TWILIO_FROM = os.getenv("TWILIO_FROM", "")
TWILIO_TO = os.getenv("TWILIO_TO", "")

# Filters
MIN_PRICE = _f("MIN_PRICE", 50)
MAX_PRICE = _f("MAX_PRICE", 5000)
MIN_VOLUME = _i("MIN_VOLUME", 100_000)
TARGET_PCT_MIN = _f("TARGET_PCT_MIN", 5)
TARGET_PCT_MAX = _f("TARGET_PCT_MAX", 15)
TOP_N = _i("TOP_N", 10)

# Ultra-High Accuracy Filters
CHECK_NIFTY_TREND = os.getenv("CHECK_NIFTY_TREND", "true").lower() == "true"
MIN_RR_RATIO = _f("MIN_RR_RATIO", 2.0)
MIN_TURNOVER_CR = _f("MIN_TURNOVER_CR", 10.0)

# Schedule
RUN_TIME = os.getenv("RUN_TIME", "15:35")

# Cache
CACHE_DIR = ROOT / "cache"
CACHE_DIR.mkdir(exist_ok=True)
LOG_DIR = ROOT / "logs"
LOG_DIR.mkdir(exist_ok=True)
