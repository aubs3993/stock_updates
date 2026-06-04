"""Environment variables and constants for stock_updates."""

import os
import sys
from datetime import timezone

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover - zoneinfo is stdlib on 3.9+
    ZoneInfo = None

# --- SEC EDGAR -------------------------------------------------------------

SEC_TICKER_MAP_URL = "https://www.sec.gov/files/company_tickers.json"
SEC_SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik:010d}.json"
SEC_ARCHIVES_BASE = "https://www.sec.gov/Archives/edgar/data"

# SEC fair access: max 10 requests/second. We pace well under that and back
# off on HTTP 429.
SEC_REQUEST_INTERVAL_SECONDS = 0.12
SEC_MAX_RETRIES = 3
SEC_TIMEOUT_SECONDS = 30

# Material form types (see CLAUDE.md "EDGAR first"). "/A" amendments of any
# listed form also count; 424B* matches by prefix. D/DRS/FWP/8-A12* cover
# private raises and the IPO paper trail (e.g., pre-IPO watchlist entries).
MATERIAL_FORMS = {
    "8-K", "10-K", "10-Q", "S-1", "S-3", "S-4", "SC 13D", "SC 13G",
    "3", "4", "5", "DEF 14A", "6-K", "20-F",
    "D", "DRS", "FWP", "8-A12B", "8-A12G",
}
MATERIAL_FORM_PREFIXES = ("424B",)

# Max characters of stripped filing text included as an excerpt for
# summarization, and a per-company cap on excerpt fetches to bound runtime.
EXCERPT_MAX_CHARS = 6000
EXCERPT_FETCH_LIMIT = 25

# --- Lookback windows ------------------------------------------------------

DEFAULT_LOOKBACK_DAYS = 7
DEFAULT_BASELINE_DAYS = 30

# --- Email (Resend) ---------------------------------------------------------

RESEND_SEND_URL = "https://api.resend.com/emails"
EMAIL_TIMEOUT_SECONDS = 30

# --- Environment variables ---------------------------------------------------

REQUIRED_ENV_VARS = (
    "SEC_USER_AGENT",
    "RECIPIENT_EMAIL",
    "SENDER_EMAIL",
    "EMAIL_API_KEY",
    "NOTION_PARENT_PAGE_ID",
)

DEFAULT_TIMEZONE = "America/New_York"


def env(name):
    """Return a stripped env var value, or '' if unset."""
    return os.environ.get(name, "").strip()


def require_env(name):
    """Return the env var value or exit loudly if it is missing."""
    value = env(name)
    if not value:
        print(f"ERROR: required environment variable {name} is not set", file=sys.stderr)
        sys.exit(2)
    return value


def missing_env_vars():
    """Names of required env vars that are unset/blank."""
    return [name for name in REQUIRED_ENV_VARS if not env(name)]


def get_timezone_name():
    return env("TIMEZONE") or DEFAULT_TIMEZONE


def get_timezone():
    """Resolve TIMEZONE to a tzinfo, falling back loudly rather than crashing."""
    name = get_timezone_name()
    if ZoneInfo is not None:
        for candidate in (name, DEFAULT_TIMEZONE):
            try:
                return ZoneInfo(candidate)
            except Exception:
                print(f"WARNING: could not load timezone {candidate!r}", file=sys.stderr)
    print("WARNING: falling back to UTC", file=sys.stderr)
    return timezone.utc
