"""Lead enrichment completeness helpers."""

from __future__ import annotations

import re
from typing import Any


EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def normalize_email(value: str) -> str:
    return (value or "").strip().lower()


def is_valid_email(value: str) -> bool:
    email = normalize_email(value)
    if not EMAIL_RE.match(email):
        return False
    local, _, domain = email.partition("@")
    if re.search(r"\.(png|jpe?g|gif|webp|svg|css|js|pdf|mp4|mov|zip)$", domain, re.I):
        return False
    if re.search(r"@\d+x[\w.-]*\.(png|jpe?g|webp|gif)$", email, re.I):
        return False
    if local.endswith(("-1536x1536", "-1024x863", "_2x", "@2x")):
        return False
    return True


def merge_contact_candidates(lead: dict[str, Any], candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    existing = lead.get("contact_candidates") or []
    by_email: dict[str, dict[str, Any]] = {}
    for item in existing + candidates:
        email = normalize_email(item.get("email") or item.get("value") or "")
        if not is_valid_email(email):
            continue
        merged = dict(item)
        merged["email"] = email
        merged["value"] = email
        merged.setdefault("source_provider", "unknown")
        merged.setdefault("source_url", "")
        merged.setdefault("confidence", "medium")
        merged["selected"] = email == normalize_email(lead.get("contact_email", ""))
        by_email[email] = {**by_email.get(email, {}), **merged}
    return list(by_email.values())


def merge_linkedin_candidates(lead: dict[str, Any], candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    existing = lead.get("linkedin_candidates") or []
    by_url: dict[str, dict[str, Any]] = {}
    for item in existing + candidates:
        url = (item.get("url") or "").strip()
        if not url:
            continue
        key = url.lower().rstrip("/")
        merged = dict(item)
        merged.setdefault("kind", "company")
        merged.setdefault("name", "")
        merged.setdefault("title", "")
        merged.setdefault("source_provider", "unknown")
        merged.setdefault("confidence", "medium")
        merged["selected"] = key == (lead.get("linkedin_url") or "").strip().lower().rstrip("/")
        by_url[key] = {**by_url.get(key, {}), **merged}
    return list(by_url.values())


# Generic domains/fragments that must never be auto-promoted as a contact email.
# Mirrors the skip set used in sources/firecrawl.py and server.py scrape_contact.
_SKIP_EMAIL_FRAGMENTS = (
    "noreply", "no-reply", "donotreply", "do-not-reply", "bounce", "mailer-daemon",
    "postmaster", "sentry", "wixpress.com", "squarespace.com", "shopify.com",
    "amazonaws.com", "example.com", "yourdomain", "domain.com", "w3.org",
    "schema.org", "google.com", "facebook.com", "instagram.com", "twitter.com",
    "sentry.io", "wordpress.com",
)

# Local-parts that signal a real person (rank above generic inboxes).
_ROLE_LOCAL_PARTS = (
    "founder", "owner", "ceo", "director", "principal", "partner",
    "manager", "head", "marketing", "brand", "creative", "design",
)

# Generic-but-acceptable inboxes on the company's own domain.
_GENERIC_LOCAL_PARTS = ("info", "hello", "contact", "hi", "mail", "office", "studio", "team")


def _email_domain(value: str) -> str:
    return normalize_email(value).partition("@")[2]


def _website_domain(website: str) -> str:
    """Strip scheme, www, path and port from a website URL to a bare domain."""
    host = re.sub(r"^https?://", "", (website or "").strip(), flags=re.I)
    host = host.split("/")[0].split("?")[0].split(":")[0]
    host = host.strip().lower().rstrip(".")
    if host.startswith("www."):
        host = host[4:]
    return host


def _domains_match(email_domain: str, site_domain: str) -> bool:
    """True when the email domain is the site domain or a subdomain of it."""
    if not email_domain or not site_domain:
        return False
    return email_domain == site_domain or email_domain.endswith("." + site_domain)


def _candidate_rank(email: str) -> int:
    """Lower is better. Person/role inboxes beat generic inboxes."""
    local = normalize_email(email).partition("@")[0]
    if any(part in local for part in _ROLE_LOCAL_PARTS):
        return 0
    if local in _GENERIC_LOCAL_PARTS:
        return 2
    # Looks like a personal name (no digits, has a letter) -> treat as person.
    if local and not any(ch.isdigit() for ch in local):
        return 1
    return 3


_CONFIDENCE_RANK = {"high": 0, "verified": 0, "medium": 1, "low": 2}


def promote_best_contact_email(lead: dict[str, Any]) -> bool:
    """Auto-fill lead['contact_email'] from discovered candidates.

    Only promotes an email on the company's own domain (or a subdomain), so a
    third-party address scraped from the page is never used. Person/role inboxes
    are preferred over generic ones, then by candidate confidence. Off-domain-only
    leads are left untouched for manual review.

    Returns True if an email was promoted, False otherwise.
    """
    if (lead.get("contact_email") or "").strip():
        return False

    site_domain = _website_domain(lead.get("website", ""))
    if not site_domain:
        return False

    # Gather every candidate email we know about, with any confidence hint.
    seen: dict[str, str] = {}  # email -> confidence
    for c in lead.get("contact_candidates") or []:
        email = normalize_email(c.get("email") or c.get("value") or "")
        if email:
            seen.setdefault(email, str(c.get("confidence") or "medium").lower())
    for email in [lead.get("contact_page_email"), *(lead.get("contact_page_emails") or [])]:
        email = normalize_email(email or "")
        if email:
            seen.setdefault(email, "medium")

    viable = []
    for email, confidence in seen.items():
        if not is_valid_email(email):
            continue
        if any(frag in email for frag in _SKIP_EMAIL_FRAGMENTS):
            continue
        if not _domains_match(_email_domain(email), site_domain):
            continue
        viable.append((email, confidence))

    if not viable:
        return False

    viable.sort(key=lambda ec: (
        _candidate_rank(ec[0]),
        _CONFIDENCE_RANK.get(ec[1], 1),
        ec[0],
    ))
    lead["contact_email"] = viable[0][0]
    sync_selected_candidates(lead)
    return True


def sync_selected_candidates(lead: dict[str, Any]) -> None:
    selected_email = normalize_email(lead.get("contact_email", ""))
    for c in lead.get("contact_candidates") or []:
        c["selected"] = bool(selected_email and normalize_email(c.get("email") or c.get("value") or "") == selected_email)

    selected_linkedin = (lead.get("linkedin_url") or "").strip().lower().rstrip("/")
    for c in lead.get("linkedin_candidates") or []:
        c["selected"] = bool(selected_linkedin and (c.get("url") or "").strip().lower().rstrip("/") == selected_linkedin)


def audit_lead(lead: dict[str, Any]) -> dict[str, Any]:
    missing = []
    contact_candidates = lead.get("contact_candidates") or []
    linkedin_candidates = lead.get("linkedin_candidates") or []
    linkedin_profiles = lead.get("linkedin_profiles") or []

    has_email = bool(lead.get("contact_email") or lead.get("contact_page_email") or contact_candidates)
    has_company_linkedin = bool(
        lead.get("apollo_linkedin_url")
        or any((c.get("kind") == "company") for c in linkedin_candidates)
    )
    has_decision_maker = bool(lead.get("decision_maker") or any(p.get("name") for p in linkedin_profiles))
    has_person_linkedin = bool(
        lead.get("linkedin_url")
        or any((c.get("kind") == "person") for c in linkedin_candidates)
        or any(p.get("url") for p in linkedin_profiles)
    )

    if not lead.get("website"):
        missing.append("website")
    if not lead.get("website_summary"):
        missing.append("website_summary")
    if not has_email:
        missing.append("email")
    if not has_company_linkedin:
        missing.append("company_linkedin")
    if not has_decision_maker:
        missing.append("decision_maker")
    if not has_person_linkedin:
        missing.append("person_linkedin")
    if not lead.get("company_size") and not lead.get("industry_apollo") and not lead.get("estimated_revenue"):
        missing.append("apollo_company_data")

    provider_status = lead.get("enrichment_status") or {}
    firecrawl = provider_status.get("firecrawl") or {}
    apollo_org = provider_status.get("apollo_organization") or {}
    apollo_people = provider_status.get("apollo_people") or {}

    critical_missing = {"website_summary", "email", "company_linkedin", "decision_maker", "person_linkedin"}
    found_count = len(critical_missing - set(missing))
    if found_count >= 4:
        status = "complete"
    elif found_count >= 2 or lead.get("enriched_at"):
        status = "partial"
    else:
        status = "missing"

    return {
        "status": status,
        "missing_fields": missing,
        "found": {
            "website": bool(lead.get("website")),
            "website_summary": bool(lead.get("website_summary")),
            "email": has_email,
            "company_linkedin": has_company_linkedin,
            "decision_maker": has_decision_maker,
            "person_linkedin": has_person_linkedin,
            "apollo_company_data": "apollo_company_data" not in missing,
        },
        "providers": {
            "firecrawl": firecrawl,
            "apollo_organization": apollo_org,
            "apollo_people": apollo_people,
        },
        "contact_candidate_count": len(contact_candidates),
        "linkedin_candidate_count": len(linkedin_candidates),
    }


def audit_many(leads: list[dict[str, Any]]) -> dict[str, Any]:
    counts = {"complete": 0, "partial": 0, "missing": 0}
    missing_counts: dict[str, int] = {}
    lead_summaries = []
    for lead in leads:
        audit = audit_lead(lead)
        counts[audit["status"]] += 1
        for field in audit["missing_fields"]:
            missing_counts[field] = missing_counts.get(field, 0) + 1
        lead_summaries.append({
            "id": lead.get("id", ""),
            "name": lead.get("name", ""),
            "priority": lead.get("priority", ""),
            "status": lead.get("status", ""),
            "audit": audit,
        })
    return {
        "total": len(leads),
        "counts": counts,
        "missing_counts": missing_counts,
        "leads": lead_summaries,
    }

