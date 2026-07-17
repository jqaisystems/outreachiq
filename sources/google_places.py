"""
Google Places API (New) - Text Search client.
Returns prospect dicts ready to save to prospects.json.

Free tier: $200/month credit, approximately 11,700 Basic searches/month.
Only Basic fields are requested to avoid Advanced pricing tier.
"""

import time
import requests
from config import GOOGLE_PLACES_API_KEY, MAX_LIMIT, INDUSTRY_LABELS
from enrich.tracking import log_api_usage

_URL = "https://places.googleapis.com/v1/places:searchText"

# Basic tier fields only - never add photos/reviews (triggers Advanced pricing)
_FIELD_MASK = ",".join([
    "nextPageToken",
    "places.id",
    "places.displayName",
    "places.formattedAddress",
    "places.addressComponents",
    "places.internationalPhoneNumber",
    "places.websiteUri",
    "places.rating",
    "places.userRatingCount",
    "places.googleMapsUri",
    "places.businessStatus",
])


def search(query: str, location: str, industry: str, limit: int = 20) -> list[dict]:
    """
    Searches Google Places for businesses matching query + location.
    Returns a list of raw prospect dicts (not yet saved to JSON).

    Args:
        query:    Search term, e.g. "real estate agency luxury property"
        location: Location string, e.g. "Dubai, UAE"
        industry: Industry key from config.INDUSTRY_QUERIES
        limit:    Max results (hard cap: 60 via pagination)
    """
    if not GOOGLE_PLACES_API_KEY:
        raise EnvironmentError(
            "GOOGLE_PLACES_API_KEY not set in .env\n"
            "Get a free key at console.cloud.google.com and enable 'Places API (New)'"
        )

    limit = min(limit, MAX_LIMIT)
    full_query = f"{query} in {location}"
    prospects = []
    next_page_token = None

    while len(prospects) < limit:
        page_size = min(20, limit - len(prospects))
        page = _fetch_page(full_query, page_size, next_page_token)
        places = page.get("places", [])

        for place in places:
            if len(prospects) >= limit:
                break
            p = _place_to_prospect(place, industry, location)
            if p:
                prospects.append(p)

        next_page_token = page.get("nextPageToken")
        if not next_page_token or not places:
            break
        time.sleep(2)  # Google requires a pause between paginated requests

    return prospects


def _fetch_page(query: str, page_size: int, page_token: str | None) -> dict:
    body = {"textQuery": query, "pageSize": page_size, "languageCode": "en"}
    if page_token:
        body["pageToken"] = page_token

    headers = {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": GOOGLE_PLACES_API_KEY,
        "X-Goog-FieldMask": _FIELD_MASK,
    }

    start = time.perf_counter()
    try:
        r = requests.post(_URL, json=body, headers=headers, timeout=30)
        r.raise_for_status()
    except requests.HTTPError as e:
        duration = int((time.perf_counter() - start) * 1000)
        detail = ""
        try:
            detail = e.response.json()
        except Exception:
            pass
        log_api_usage(
            provider="google_places",
            endpoint="searchText",
            status="error",
            domain=query,
            duration_ms=duration,
            estimated_credits=1,
            error=f"HTTP {e.response.status_code}: {detail}",
        )
        raise RuntimeError(_friendly_http_error(e.response.status_code, detail)) from e
    except requests.ConnectionError as e:
        duration = int((time.perf_counter() - start) * 1000)
        log_api_usage(
            provider="google_places",
            endpoint="searchText",
            status="error",
            domain=query,
            duration_ms=duration,
            estimated_credits=1,
            error=str(e),
        )
        raise RuntimeError("Cannot connect to Google Places API.") from e

    duration = int((time.perf_counter() - start) * 1000)
    payload = r.json()
    log_api_usage(
        provider="google_places",
        endpoint="searchText",
        status="ok",
        domain=query,
        duration_ms=duration,
        fields_returned=["places", "nextPageToken"] if payload.get("nextPageToken") else ["places"],
        result_count=len(payload.get("places", [])),
        estimated_credits=1,
    )
    return payload


def _friendly_http_error(status_code: int, detail) -> str:
    if not isinstance(detail, dict):
        return f"Google Places API HTTP {status_code}: {detail}"

    error = detail.get("error", {})
    message = error.get("message", "")
    reason = ""
    caller_ip = ""
    for item in error.get("details", []):
        metadata = item.get("metadata", {}) if isinstance(item, dict) else {}
        reason = reason or item.get("reason", "")
        caller_ip = caller_ip or metadata.get("callerIp", "")

    if status_code == 403 and reason == "API_KEY_IP_ADDRESS_BLOCKED":
        ip_text = f" Current IP: {caller_ip}." if caller_ip else ""
        return (
            "Google Places API key blocked by IP restriction."
            f"{ip_text} Add this IP to the key's allowed server IP addresses in Google Cloud Console, "
            "or relax the Application restrictions for local testing. Keep the API restriction limited to Places API."
        )

    if status_code == 403:
        return f"Google Places API permission denied: {message or detail}"

    return f"Google Places API HTTP {status_code}: {detail}"


def _place_to_prospect(place: dict, industry: str, location: str) -> dict | None:
    if place.get("businessStatus") == "PERMANENTLY_CLOSED":
        return None

    name = place.get("displayName", {}).get("text", "").strip()
    if not name:
        return None

    website = place.get("websiteUri", "")
    city, country = _extract_location(place.get("addressComponents", []))

    # Infer region from location string for display (e.g. "Dubai, UAE" -> "UAE")
    region = location.split(",")[-1].strip() if "," in location else location

    return {
        "id":              place.get("id", ""),
        "name":            name,
        "industry":        industry,
        "niche":           INDUSTRY_LABELS.get(industry, industry.title()),
        "region":          region,
        "address":         place.get("formattedAddress", ""),
        "city":            city,
        "country":         country,
        "phone":           place.get("internationalPhoneNumber", ""),
        "website":         website,
        "google_maps_url": place.get("googleMapsUri", ""),
        "rating":          float(place.get("rating", 0.0)),
        "review_count":    int(place.get("userRatingCount", 0)),
        "has_website":     bool(website),
        "found_at":        _now(),
        "status":          "new",
        # Scoring (filled by Claude Code via scored.json import)
        "score":            0,
        "priority":         "",
        "score_reason":     "",
        "brand_gap":        "",
        "outreach_subject": "",
        "linkedin_note":    "",
        # Contact fields
        "decision_maker":       "",
        "decision_maker_title": "",
        "contact_email":        "",
        "linkedin_url":         "",
        "linkedin_owner":       "",
        # Tracking
        "email_path":       None,
        "date_added":       _today(),
        "date_scored":      None,
        "date_sent":        None,
        "notes":            "",
        # Email variants
        "email_variants":      [],
        "trigger":             "",
        # Enrichment (future use)
        "enriched_at":        None,
        "website_summary":    None,
        "brand_signals":      None,
        "contact_page_email": None,
    }


def _extract_location(components: list[dict]) -> tuple[str, str]:
    city = country = ""
    for c in components:
        types = c.get("types", [])
        if "locality" in types or "postal_town" in types:
            city = c.get("longText", "")
        if "country" in types:
            country = c.get("longText", "")
    return city, country


def _now() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()


def _today() -> str:
    from datetime import date
    return date.today().isoformat()
