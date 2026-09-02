"""
APIx Configuration — Central settings for the Airfare Price Index prototype.
"""

from pathlib import Path
from datetime import date, timedelta

# ─── Project Paths ───────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
SCRAPED_DIR = DATA_DIR / "scraped"
STATIC_DIR = BASE_DIR / "static"
TEMPLATES_DIR = BASE_DIR / "templates"

# Ensure directories exist
SCRAPED_DIR.mkdir(parents=True, exist_ok=True)

# ─── City Pairs (DGCA High-Traffic Routes) ──────────────────────────────────
CITY_PAIRS = [
    ("DEL", "BOM"),  # Delhi → Mumbai
    ("BOM", "BLR"),  # Mumbai → Bengaluru
    ("DEL", "BLR"),  # Delhi → Bengaluru
]

# Human-readable route names
ROUTE_NAMES = {
    "DEL-BOM": "Delhi → Mumbai",
    "BOM-BLR": "Mumbai → Bengaluru",
    "DEL-BLR": "Delhi → Bengaluru",
}

# ─── Advance Purchase Windows ───────────────────────────────────────────────
ADVANCE_DAYS = [1, 15]  # T+1 (tomorrow) and T+15

def get_travel_dates() -> list[date]:
    """Return target travel dates based on advance purchase windows."""
    today = date.today()
    return [today + timedelta(days=d) for d in ADVANCE_DAYS]

# ─── Scraper Settings ───────────────────────────────────────────────────────
SCRAPER_MIN_DELAY = 3.0   # Minimum seconds between requests
SCRAPER_MAX_DELAY = 7.0   # Maximum seconds between requests
SCRAPER_MAX_REQUESTS_PER_SESSION = 20
SCRAPER_TIMEOUT_MS = 30000  # 30 second page load timeout
SCRAPER_HEADLESS = False

# ─── Data Validation & Regulatory Caps ─────────────────────────────────────
MIN_FARE_INR = 1500    # Minimum plausible domestic economy fare
MAX_FARE_INR = 25000   # Maximum plausible domestic economy fare
TAX_RATIO_ESTIMATE = 0.22  # Estimated tax portion when breakdown unavailable

# Rule 135 Upper Tariff Caps (Bharatiya Vayuyan Adhiniyam 2024 / Aircraft Rules 1937)
TARIFF_CAPS = {
    "DEL-BOM": 12000.0,
    "BOM-BLR": 10000.0,
    "DEL-BLR": 13000.0,
}

# Indian airports (subset for validation)
VALID_IATA_CODES = {
    "DEL", "BOM", "BLR", "MAA", "CCU", "HYD", "COK", "GOI", "PNQ",
    "AMD", "JAI", "LKO", "PAT", "IXC", "SXR", "GAU", "BBI", "IDR",
    "NAG", "VNS", "TRV", "IXR", "RPR", "VTZ", "IXB", "IMF", "DIB",
}

# ─── Index Calculation ──────────────────────────────────────────────────────
INDEX_BASE_VALUE = 100.0
INDEX_BASE_DATE = date(2026, 7, 28)  # 30-day baseline start date
HISTORICAL_SEED_FILE = DATA_DIR / "historical_seed.json"

# ─── Server Settings ────────────────────────────────────────────────────────
APP_TITLE = "Vayu — Airfare Price Index"
APP_DESCRIPTION = "Real-time airfare inflation tracking for MoSPI/DGCA"
APP_VERSION = "1.0.0"
HOST = "0.0.0.0"
PORT = 8000
