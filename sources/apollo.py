"""
Apollo.io client for OutreachIQ.
Uses the Organization Enrich endpoint to pull company-level signals:
size, industry, founding year, estimated revenue, keywords, LinkedIn URL.

No people-level data is pulled here. Decision-maker research is handled
by Claude Code's WebSearch during the email-writing step.
"""

import re
import time
import requests
from config import APOLLO_API_KEY, APOLLO_WEBHOOK_URL
from enrich.tracking import log_api_usage

_URL = "https://api.apollo.io/api/v1/organizations/enrich"
_PEOPLE_MATCH_URL = "https://api.apollo.io/api/v1/people/match"
_DOMAIN_RE = re.compile(r"^(?:https?://)?(?:www\.)?([^/\s]+)")


def enrich_organization(website: str, *, lead_id: str = "") -> dict:
    """
    Enrich a company using the Apollo Organization Enrich endpoint.

    Args:
        website: Full URL or bare domain, e.g. "https://pacificedgesf.com"

    Returns a dict with (all fields may be None if Apollo has no data):
        company_size        Estimated employee count (int) or band string
        industry_apollo     Industry label from Apollo
        founded_year        Year company was founded (int)
        estimated_revenue   Revenue string (e.g. "$1M-$10M")
        apollo_keywords     List of keywords (first 10)
        apollo_linkedin_url Company LinkedIn URL

    Returns {} on any failure.
    """
    if not APOLLO_API_KEY:
        return {}

    domain = _extract_domain(website)
    if not domain:
        return {}

    start = time.perf_counter()
    try:
        resp = requests.post(
            _URL,
            params={"domain": domain},
            headers={"X-Api-Key": APOLLO_API_KEY, "Content-Type": "application/json"},
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        duration = int((time.perf_counter() - start) * 1000)
        log_api_usage(
            provider="apollo",
            endpoint="organization_enrich",
            status="error",
            lead_id=lead_id,
            domain=domain,
            duration_ms=duration,
            estimated_credits=1,
            error=str(e),
        )
        print(f"[apollo] enrich failed for {domain}: {e}")
        return {}

    duration = int((time.perf_counter() - start) * 1000)
    org = data.get("organization") or {}
    log_api_usage(
        provider="apollo",
        endpoint="organization_enrich",
        status="ok" if org else "empty",
        lead_id=lead_id,
        domain=domain,
        duration_ms=duration,
        fields_returned=[k for k, v in org.items() if v is not None],
        result_count=1 if org else 0,
        estimated_credits=1,
    )
    if not org:
        return {}

    keywords = org.get("keywords") or []
    if isinstance(keywords, list):
        keywords = keywords[:10]

    return {
        "apollo_organization_id": org.get("id"),
        "company_size":       org.get("estimated_num_employees"),
        "industry_apollo":    org.get("industry"),
        "founded_year":       org.get("founded_year"),
        "estimated_revenue":  org.get("annual_revenue_printed") or org.get("organization_revenue_printed"),
        "apollo_keywords":    keywords,
        "apollo_linkedin_url": org.get("linkedin_url"),
        "apollo_organization_raw": org,
    }


def enrich_person(
    *,
    website: str = "",
    email: str = "",
    name: str = "",
    linkedin_url: str = "",
    lead_id: str = "",
    run_waterfall_email: bool = False,
) -> dict:
    """Match one known person via Apollo People Enrichment.

    This does not search for unknown founders. It only enriches a person when
    OutreachIQ already has a name, email, or LinkedIn URL to match against.
    """
    if not APOLLO_API_KEY:
        return {}

    domain = _extract_domain(website)
    params = {
        "reveal_personal_emails": "false",
        "reveal_phone_number": "false",
    }
    if email:
        params["email"] = email
    if linkedin_url:
        params["linkedin_url"] = linkedin_url
    if domain:
        params["domain"] = domain
    first_name, last_name = _split_name(name)
    if first_name:
        params["first_name"] = first_name
    if last_name:
        params["last_name"] = last_name
    if run_waterfall_email and APOLLO_WEBHOOK_URL:
        params["run_waterfall_email"] = "true"
        params["webhook_url"] = APOLLO_WEBHOOK_URL

    identifiers = {"email", "linkedin_url", "first_name", "last_name"} & set(params.keys())
    if not identifiers:
        log_api_usage(
            provider="apollo",
            endpoint="people_match",
            status="skipped",
            lead_id=lead_id,
            domain=domain,
            estimated_credits=0,
            error="No person identifiers available",
        )
        return {}

    start = time.perf_counter()
    try:
        resp = requests.post(
            _PEOPLE_MATCH_URL,
            params=params,
            headers={
                "X-Api-Key": APOLLO_API_KEY,
                "Content-Type": "application/json",
                "Cache-Control": "no-cache",
                "accept": "application/json",
            },
            timeout=20,
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        duration = int((time.perf_counter() - start) * 1000)
        log_api_usage(
            provider="apollo",
            endpoint="people_match",
            status="error",
            lead_id=lead_id,
            domain=domain,
            duration_ms=duration,
            estimated_credits=1,
            error=str(e),
        )
        return {}

    duration = int((time.perf_counter() - start) * 1000)
    person = data.get("person") or {}
    waterfall = data.get("waterfall") or {}
    log_api_usage(
        provider="apollo",
        endpoint="people_match",
        status="ok" if person else "empty",
        lead_id=lead_id,
        domain=domain,
        duration_ms=duration,
        fields_returned=[k for k, v in person.items() if v is not None],
        result_count=1 if person else 0,
        estimated_credits=1,
    )
    if not person:
        return {"apollo_person_raw": data}

    return {
        "name": person.get("name") or name,
        "title": person.get("title") or "",
        "email": person.get("email") or email,
        "email_status": person.get("email_status"),
        "linkedin_url": person.get("linkedin_url") or linkedin_url,
        "apollo_person_id": person.get("id"),
        "apollo_person_raw": person,
        "apollo_waterfall": waterfall,
    }


def _extract_domain(website: str) -> str:
    """Strip protocol, www, and path from a URL to get the bare domain."""
    if not website:
        return ""
    m = _DOMAIN_RE.match(website.strip())
    return m.group(1).lower() if m else ""


def _split_name(name: str) -> tuple[str, str]:
    parts = [p for p in (name or "").strip().split() if p]
    if not parts:
        return "", ""
    if len(parts) == 1:
        return parts[0], ""
    return parts[0], parts[-1]


if __name__ == "__main__":
    import sys
    target = sys.argv[1] if len(sys.argv) > 1 else "pacificedgesf.com"
    print(enrich_organization(target))
