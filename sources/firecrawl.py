"""
Firecrawl client for OutreachIQ.
Scrapes website content using Firecrawl's managed rendering service,
which handles JavaScript-rendered sites and returns clean markdown.
"""

import re
import time
import requests
from config import FIRECRAWL_API_KEY
from enrich.audit import is_valid_email
from enrich.tracking import log_api_usage

_URL = "https://api.firecrawl.dev/v1/scrape"
_EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}")
_SKIP_EMAILS = {
    "example.com", "yourdomain", "noreply", "no-reply", "donotreply",
    "domain.com", "sentry", "w3.org", "schema.org", "google.com",
    "facebook.com", "instagram.com", "twitter.com", "wixpress.com",
    "squarespace.com", "shopify.com", "amazonaws.com",
}

_LUXURY_WORDS = {
    "luxury", "boutique", "exclusive", "premium", "prestige", "bespoke",
    "high-end", "elite", "refined", "curated", "artisan",
}
_ESTABLISHED_WORDS = {"established", "since", "founded", "years of experience", "decade"}


# Contact subpages to check for emails (including Norwegian variants)
_CONTACT_PATHS = [
    "/contact", "/contact-us", "/kontakt", "/kontakt-oss",
    "/about", "/about-us", "/om-oss", "/om",
    "/team", "/people", "/staff",
    "/en/contact", "/en/about",
]

_SOCIAL_RE = re.compile(r"https?://[^\s)\]\"']*(?:linkedin|facebook|instagram|x\.com|twitter|youtube)[^\s)\]\"']*", re.I)


def scrape_website(url: str, *, lead_id: str = "") -> dict:
    """
    Scrape a website via Firecrawl and extract brand signals.

    Scrapes the homepage for summary and brand signals, then also checks
    common contact/about subpages for email addresses (including Norwegian
    variants like /kontakt, /om-oss).

    Returns a dict with:
        website_summary      First ~500 chars of cleaned markdown
        brand_signals        One-line heuristic summary of brand quality signals
        contact_page_email   First real email address found
        contact_page_emails  All unique real email addresses found (deduped list)

    Returns {} on any failure (network error, API error, missing key).
    """
    if not FIRECRAWL_API_KEY:
        return {}

    if not url.startswith("http"):
        url = "https://" + url

    pages = []
    errors = []
    email_sources = {}
    social_links = []

    # 1. Scrape homepage (for summary + brand signals)
    data, error = _scrape_url(url, only_main=True, lead_id=lead_id)
    if error:
        errors.append(error)
        print(f"[firecrawl] scrape failed for {url}: {error}")
        return {}

    markdown = (data.get("data") or {}).get("markdown") or ""
    if not markdown:
        return {}

    page_info = _page_info(url, data, markdown)
    pages.append(page_info)

    # Collect emails from homepage
    for e in _real_emails(markdown):
        email_sources.setdefault(e, url)
    social_links.extend(_social_links(markdown))

    # 2. Also scrape contact/about subpages for emails (best-effort)
    base = url.rstrip("/")
    for path in _CONTACT_PATHS:
        subpage_url = base + path
        sub_data, sub_error = _scrape_url(subpage_url, only_main=False, lead_id=lead_id, timeout=20)
        if sub_error:
            errors.append(sub_error)
            continue
        sub_md = (sub_data.get("data") or {}).get("markdown") or ""
        pages.append(_page_info(subpage_url, sub_data, sub_md))
        social_links.extend(_social_links(sub_md))
        for e in _real_emails(sub_md):
            email_sources.setdefault(e, subpage_url)
        # Stop once we've found emails (save API credits)
        if email_sources:
            break

    all_emails = list(email_sources.keys())
    contact_candidates = [
        {
            "email": email,
            "value": email,
            "source_provider": "firecrawl",
            "source_url": email_sources[email],
            "confidence": "high",
            "selected": False,
        }
        for email in all_emails
    ]
    linkedin_candidates = [
        {
            "kind": "company",
            "name": "",
            "title": "",
            "url": link,
            "source_provider": "firecrawl",
            "confidence": "medium",
            "selected": False,
        }
        for link in sorted({l for l in social_links if "linkedin.com" in l.lower()})
    ]

    return {
        "website_summary":     _extract_summary(markdown),
        "brand_signals":       _extract_brand_signals(markdown),
        "contact_page_email":  all_emails[0] if all_emails else "",
        "contact_page_emails": all_emails,
        "contact_candidates": contact_candidates,
        "linkedin_candidates": linkedin_candidates,
        "firecrawl_pages": pages,
        "firecrawl_errors": errors,
        "firecrawl_social_links": sorted(set(social_links)),
    }


def _scrape_url(url: str, *, only_main: bool, lead_id: str = "", timeout: int = 30) -> tuple[dict, str]:
    start = time.perf_counter()
    try:
        resp = requests.post(
            _URL,
            json={"url": url, "formats": ["markdown"], "onlyMainContent": only_main},
            headers={"Authorization": f"Bearer {FIRECRAWL_API_KEY}"},
            timeout=timeout,
        )
        duration = int((time.perf_counter() - start) * 1000)
        if not resp.ok:
            error = f"HTTP {resp.status_code}: {resp.text[:250]}"
            log_api_usage(
                provider="firecrawl",
                endpoint="scrape",
                status="error",
                lead_id=lead_id,
                domain=url,
                duration_ms=duration,
                estimated_credits=1,
                error=error,
            )
            return {}, error
        data = resp.json()
        md = (data.get("data") or {}).get("markdown") or ""
        log_api_usage(
            provider="firecrawl",
            endpoint="scrape",
            status="ok",
            lead_id=lead_id,
            domain=url,
            duration_ms=duration,
            fields_returned=[k for k, v in (data.get("data") or {}).items() if v],
            result_count=len(_real_emails(md)),
            estimated_credits=1,
        )
        return data, ""
    except Exception as e:
        duration = int((time.perf_counter() - start) * 1000)
        error = str(e)
        log_api_usage(
            provider="firecrawl",
            endpoint="scrape",
            status="error",
            lead_id=lead_id,
            domain=url,
            duration_ms=duration,
            estimated_credits=1,
            error=error,
        )
        return {}, error


def _page_info(url: str, data: dict, markdown: str) -> dict:
    payload = data.get("data") or {}
    metadata = payload.get("metadata") or {}
    return {
        "url": url,
        "title": metadata.get("title") or metadata.get("ogTitle") or "",
        "metadata": metadata,
        "markdown_chars": len(markdown),
        "markdown_excerpt": _extract_summary(markdown),
        "emails": _real_emails(markdown),
        "social_links": _social_links(markdown),
    }


def _extract_summary(md: str) -> str:
    """Return first ~500 chars of non-empty markdown lines."""
    lines = [l.strip() for l in md.splitlines() if l.strip()]
    excerpt = " ".join(lines)
    return excerpt[:500]


def _extract_brand_signals(md: str) -> str:
    """
    Build a one-line string summarising brand quality signals visible in the markdown.
    Examples: "luxury keywords, mailto present, 4 headings, form-heavy page"
    """
    lower = md.lower()
    signals = []

    # Tone signals
    luxury_hits = [w for w in _LUXURY_WORDS if w in lower]
    if luxury_hits:
        signals.append(f"luxury keywords ({', '.join(luxury_hits[:3])})")

    if any(w in lower for w in _ESTABLISHED_WORDS):
        signals.append("established language")

    # Contact signals
    emails = _real_emails(md)
    if emails:
        signals.append("mailto present")

    # Heading count (rough proxy for content depth)
    heading_count = md.count("\n#")
    if heading_count >= 5:
        signals.append(f"{heading_count} headings (content-rich)")
    elif heading_count == 0:
        signals.append("no headings (sparse content)")

    # Form-heavy page
    form_words = sum(1 for w in ["contact us", "get in touch", "send message", "submit"] if w in lower)
    if form_words >= 2:
        signals.append("form-heavy page")

    # Social proof
    if any(w in lower for w in ["award", "featured in", "as seen", "recognition"]):
        signals.append("social proof present")

    if not signals:
        return "no strong brand signals detected"
    return ", ".join(signals)


def _extract_email(md: str) -> str:
    """Return first real email address found in the markdown, or empty string."""
    return next(iter(_real_emails(md)), "")


def _real_emails(md: str) -> list:
    found = []
    for e in _EMAIL_RE.findall(md):
        e_low = e.lower()
        if not any(skip in e_low for skip in _SKIP_EMAILS) and is_valid_email(e_low):
            found.append(e_low)
    return list(dict.fromkeys(found))


def _social_links(md: str) -> list:
    links = []
    for raw in _SOCIAL_RE.findall(md or ""):
        link = raw.rstrip(".,;)")
        links.append(link)
    return list(dict.fromkeys(links))


if __name__ == "__main__":
    import sys
    target = sys.argv[1] if len(sys.argv) > 1 else "https://pacificedgesf.com"
    print(scrape_website(target))
