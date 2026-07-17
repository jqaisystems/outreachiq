"""
OutreachIQ - Configuration
Loads .env and exports all constants used across the app.
"""

import os
import time
from dotenv import load_dotenv

load_dotenv()

# ---------------------------------------------------------------------------
# API Keys
# ---------------------------------------------------------------------------
GOOGLE_PLACES_API_KEY: str = os.getenv("GOOGLE_PLACES_API_KEY", "")
FIRECRAWL_API_KEY:     str = os.getenv("FIRECRAWL_API_KEY", "")
APOLLO_API_KEY:        str = os.getenv("APOLLO_API_KEY", "")
APOLLO_WEBHOOK_URL:    str = os.getenv("APOLLO_WEBHOOK_URL", "")

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
BASE_DIR       = os.path.dirname(os.path.abspath(__file__))
DATA_DIR       = os.path.join(BASE_DIR, "data")
PROSPECTS_JSON = os.path.join(DATA_DIR, "prospects.json")
ICP_RECOMMENDATIONS_JSON = os.path.join(DATA_DIR, "icp_recommendations.json")
EXPORTS_DIR    = os.path.join(DATA_DIR, "exports")
EMAILS_DIR     = os.path.join(BASE_DIR, "emails")
ENRICHMENT_DIR = os.path.join(DATA_DIR, "enrichment")
API_USAGE_JSONL = os.path.join(DATA_DIR, "api_usage.jsonl")
EMAIL_LOG_MD    = os.path.join(BASE_DIR, "email-log.md")
# Optional operator memory file (profile, tone notes, what works). Defaults to
# an in-repo memory.md; copy memory.example.md to memory.md to start one.
MEMORY_MD       = os.getenv("OUTREACH_MEMORY_PATH", os.path.join(BASE_DIR, "memory.md"))
DO_NOT_CONTACT_JSON = os.path.join(DATA_DIR, "do_not_contact.json")
SEND_LOCK_JSON  = os.path.join(DATA_DIR, "send_lock.json")
SEND_COUNTER_JSON = os.path.join(DATA_DIR, "send_counter.json")
SEND_ACTIVE_JSON = os.path.join(DATA_DIR, "send_active.json")

# ---------------------------------------------------------------------------
# Gmail sending (Gmail API, OAuth2) - minimal scopes: send + read replies only.
# No gmail.modify, so the app can never delete or alter mailbox contents.
# ---------------------------------------------------------------------------
GMAIL_CLIENT_SECRET_FILE = os.path.join(BASE_DIR, "client_secret.json")
GMAIL_TOKEN_FILE         = os.path.join(BASE_DIR, "token.json")
GMAIL_SCOPES             = [
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/gmail.readonly",
]
# Optional explicit "from" address; otherwise Gmail uses the authorized account.
GMAIL_SENDER             = os.getenv("GMAIL_SENDER", "")

# ---------------------------------------------------------------------------
# Sending safety throttle
# ---------------------------------------------------------------------------
SEND_DELAY_SECONDS = float(os.getenv("SEND_DELAY_SECONDS", "20"))   # gap between sends
DAILY_SEND_CAP     = int(os.getenv("DAILY_SEND_CAP", "30"))         # max sends per day
FOLLOW_UP_DAYS     = int(os.getenv("FOLLOW_UP_DAYS", "5"))          # days before follow-up due
REPLY_POLL_MINUTES = int(os.getenv("REPLY_POLL_MINUTES", "360"))    # auto reply/bounce check while server runs (0 = off)

# Email signature appended to every outgoing email (canonical, server-side).
# Set the SIGNATURE_* variables in .env, or override the whole block with
# EMAIL_SIGNATURE (use \n for line breaks).
SIGNATURE_NAME    = os.getenv("SIGNATURE_NAME", "Your Name")
SIGNATURE_TITLE   = os.getenv("SIGNATURE_TITLE", "Your Title")
SIGNATURE_WEBSITE = os.getenv("SIGNATURE_WEBSITE", "www.example.com")
SIGNATURE_EMAIL   = os.getenv("SIGNATURE_EMAIL", "you@example.com")
SIGNATURE_PHONE   = os.getenv("SIGNATURE_PHONE", "")

EMAIL_SIGNATURE = os.getenv("EMAIL_SIGNATURE", "").replace("\\n", "\n") or (
    "Kind Regards,\n"
    "____________________________\n\n"
    f"{SIGNATURE_NAME} - {SIGNATURE_TITLE}\n"
    f"W | {SIGNATURE_WEBSITE}\n\n"
    f"E| {SIGNATURE_EMAIL}"
    + (f" - P| {SIGNATURE_PHONE}" if SIGNATURE_PHONE else "")
)

# ---------------------------------------------------------------------------
# Search limits
# ---------------------------------------------------------------------------
DEFAULT_LIMIT = 20
MAX_LIMIT     = 60   # Google Places API hard cap via pagination

# Industry to search query mapping
INDUSTRY_QUERIES: dict[str, str] = {
    "real_estate":   "real estate developer agency luxury property",
    "construction":  "construction company general contractor builder",
    "architecture":  "architecture firm interior design studio",
    "hospitality":   "boutique hotel restaurant luxury dining",
    "finance":       "financial advisory wealth management accounting firm",
    "law":           "law firm legal services attorney",
    "health":        "private clinic wellness center medical practice",
    "beauty":        "luxury spa beauty salon cosmetic clinic",
    "sports":        "sports brand fitness studio athlete management",
    "tech":          "SaaS company software startup technology firm",
    "luxury":        "luxury brand lifestyle premium goods",
    "food":          "food brand packaging premium food producer",
    "agency":        "marketing agency design agency creative studio branding agency digital agency",
    "branding":      "branding agency brand design studio brand identity firm brand consultancy",
}

# Human-readable niche labels
INDUSTRY_LABELS: dict[str, str] = {
    "real_estate":  "Real Estate",
    "construction": "Construction",
    "architecture": "Architecture & Interior Design",
    "hospitality":  "Food & Hospitality",
    "finance":      "Finance",
    "law":          "Law & Legal",
    "health":       "Health & Wellness",
    "beauty":       "Beauty & Spa",
    "sports":       "Sports & Entertainment",
    "tech":         "Tech & SaaS",
    "luxury":       "Luxury & Lifestyle",
    "food":         "Food & Packaging",
    "agency":       "Marketing & Design Agencies",
    "branding":     "Branding & Design Agencies",
}

# Service-led prospecting, ordered by your offer priority. This is an example
# service catalog: replace the labels and presets below with your own offers.
SERVICE_FOCUS_LABELS: dict[str, str] = {
    "branding": "Branding",
    "web_design": "Web Design",
    "editorial_print": "Editorial & Print",
    "ai_systems": "AI Automation Systems",
}

SERVICE_OFFER_LABELS: dict[str, str] = {
    "branding": "Brand Identity",
    "web_design": "Web Design",
    "editorial_print": "Editorial & Print",
    "ai_systems": "AI Automation Systems",
}

SERVICE_MIX_LABELS: dict[str, str] = {
    "smart_mix": "Smart Mix",
    "branding_only": "Branding Only",
    "branding_web": "Branding + Web",
    "branding_web_print": "Branding + Web + Print",
    "all_services": "All Services",
}

SEARCH_MODE_LABELS: dict[str, str] = {
    "direct_client": "Direct Client",
    "agency_partner": "Agency Partner",
}

MARKET_PRESETS: dict[str, dict] = {
    "premium_global": {
        "label": "Premium Global",
        "regions": ["USA", "UAE", "UK", "Switzerland", "Singapore", "Nordics"],
        "default_locations": ["Dubai, UAE", "London, UK", "Zurich, Switzerland", "Singapore", "Austin, USA"],
    },
    "europe_first": {
        "label": "Europe First",
        "regions": ["Portugal", "Spain", "France", "Switzerland", "UK", "Nordics"],
        "default_locations": ["Lisbon, Portugal", "Madrid, Spain", "Paris, France", "Zurich, Switzerland", "London, UK"],
    },
    "us_only": {
        "label": "US Only",
        "regions": ["USA"],
        "default_locations": ["Austin, USA", "Miami, USA", "Los Angeles, USA", "New York, USA", "Scottsdale, USA"],
    },
}

SERVICE_SEARCH_PRESETS: dict[str, dict[str, list[dict[str, str]]]] = {
    "branding": {
        "direct_client": [
            {"label": "Luxury Real Estate", "industry": "real_estate", "query": "luxury real estate brokerage property developer"},
            {"label": "Architecture & Interiors", "industry": "architecture", "query": "architecture firm interior design studio luxury"},
            {"label": "Boutique Hospitality", "industry": "hospitality", "query": "boutique hotel hospitality group luxury restaurant"},
            {"label": "Construction & Developers", "industry": "construction", "query": "custom home builder property developer construction company"},
            {"label": "Finance & Law", "industry": "finance", "query": "wealth management financial advisory boutique law firm"},
            {"label": "Luxury & Lifestyle", "industry": "luxury", "query": "luxury lifestyle brand premium goods"},
            {"label": "Health & Beauty", "industry": "beauty", "query": "luxury spa cosmetic clinic private wellness clinic"},
        ],
        "agency_partner": [
            {"label": "Branding Studios", "industry": "branding", "query": "branding studio brand identity agency boutique"},
            {"label": "Creative Agencies", "industry": "agency", "query": "creative agency brand design studio"},
            {"label": "Marketing Agencies", "industry": "agency", "query": "marketing agency design services boutique"},
        ],
    },
    "web_design": {
        "direct_client": [
            {"label": "Premium Services", "industry": "luxury", "query": "premium service business luxury consultancy"},
            {"label": "Boutique Hospitality", "industry": "hospitality", "query": "boutique hotel restaurant hospitality group"},
            {"label": "Real Estate Teams", "industry": "real_estate", "query": "real estate team luxury property agency"},
            {"label": "Architecture Studios", "industry": "architecture", "query": "architecture studio interior design firm"},
            {"label": "Clinics", "industry": "health", "query": "private clinic wellness center cosmetic clinic"},
            {"label": "Consultants", "industry": "finance", "query": "boutique consultancy advisory firm"},
            {"label": "Luxury Retailers", "industry": "luxury", "query": "luxury retailer premium showroom"},
        ],
        "agency_partner": [
            {"label": "Web Agencies", "industry": "agency", "query": "web design agency website studio boutique"},
            {"label": "Digital Studios", "industry": "agency", "query": "digital agency UI design studio"},
        ],
    },
    "editorial_print": {
        "direct_client": [
            {"label": "Hospitality Groups", "industry": "hospitality", "query": "hospitality group boutique hotel restaurant group"},
            {"label": "Real Estate Developers", "industry": "real_estate", "query": "real estate developer luxury property"},
            {"label": "Construction Firms", "industry": "construction", "query": "construction company custom home builder"},
            {"label": "Finance Firms", "industry": "finance", "query": "wealth management financial advisory firm"},
            {"label": "Events", "industry": "sports", "query": "premium events company hospitality events"},
            {"label": "Premium Product Brands", "industry": "food", "query": "premium food brand packaging producer"},
        ],
        "agency_partner": [
            {"label": "Print Design Studios", "industry": "agency", "query": "editorial design studio print design agency"},
            {"label": "Brand Collateral Agencies", "industry": "branding", "query": "brand collateral design agency"},
        ],
    },
    "ai_systems": {
        "direct_client": [
            {"label": "Content-heavy Businesses", "industry": "tech", "query": "content marketing team ecommerce business"},
            {"label": "Ecommerce Operators", "industry": "tech", "query": "ecommerce company premium brand"},
            {"label": "Internal Operations Teams", "industry": "construction", "query": "operations heavy construction company"},
        ],
        "agency_partner": [
            {"label": "Creative Teams", "industry": "agency", "query": "creative agency content production studio"},
            {"label": "Social Media Managers", "industry": "agency", "query": "social media marketing agency"},
            {"label": "Digital Agencies", "industry": "agency", "query": "digital agency automation content operations"},
        ],
    },
}

# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------
_GMAIL_STATE_LABELS = {
    "ok":               "OK",
    "token_invalid":    "EXPIRED (run: python authorize_gmail.py)",
    "not_authorized":   "NEEDS AUTH (run: python authorize_gmail.py)",
    "no_client_secret": "MISSING client_secret.json",
    "libs_missing":     "MISSING google libraries (pip install -r requirements.txt)",
}

# gmail_status() refreshes the OAuth token over the network (~1s), and
# validate_keys() runs on every /api/stats poll, so the result is cached.
# The cache key is token.json's mtime: re-running authorize_gmail.py rewrites
# the file and invalidates the cache immediately, so a fresh auth shows up at
# once rather than after the TTL.
_GMAIL_STATUS_TTL = 60.0
_gmail_status_cache: dict = {"key": None, "value": None, "at": 0.0}


def gmail_status() -> str:
    """Real Gmail authorization status, not just 'does token.json exist'.

    A present-but-revoked token reports EXPIRED here, so the dashboard can warn
    before a send is attempted instead of failing at send time.
    """
    if not os.path.exists(GMAIL_TOKEN_FILE):
        return _GMAIL_STATE_LABELS["not_authorized" if os.path.exists(GMAIL_CLIENT_SECRET_FILE)
                                   else "no_client_secret"]
    try:
        key = os.path.getmtime(GMAIL_TOKEN_FILE)
    except OSError:
        key = None

    now = time.monotonic()
    cache = _gmail_status_cache
    if cache["key"] == key and cache["value"] and (now - cache["at"]) < _GMAIL_STATUS_TTL:
        return cache["value"]

    try:
        # Lazy import: mailer.gmail_client imports config, so a module-level
        # import here would be circular.
        from mailer import gmail_client
        state = gmail_client.status().get("state", "")
        value = _GMAIL_STATE_LABELS.get(state, f"ERROR ({state or 'unknown'})")
    except Exception as e:
        value = f"UNKNOWN (check failed: {type(e).__name__})"

    cache.update(key=key, value=value, at=now)
    return value


def validate_keys() -> dict[str, str]:
    return {
        "google_places": "OK" if GOOGLE_PLACES_API_KEY else "MISSING",
        "firecrawl":     "OK" if FIRECRAWL_API_KEY     else "MISSING (optional)",
        "apollo":        "OK" if APOLLO_API_KEY         else "MISSING (optional)",
        "gmail":         gmail_status(),
    }
