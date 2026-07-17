"""
Enrichment pipeline orchestrator.
Calls Firecrawl (website scrape) and Apollo (org data) for a single lead,
merges results into the lead dict, and sets enriched_at.

Usage:
    from enrich.pipeline import enrich_lead
    lead = enrich_lead(lead)

Best-effort: exceptions per service are caught and logged. The lead is
always returned (with whatever fields were successfully populated).
"""

from datetime import datetime, timezone

from enrich.audit import (
    audit_lead,
    is_valid_email,
    merge_contact_candidates,
    merge_linkedin_candidates,
    sync_selected_candidates,
)
from enrich.tracking import save_provider_snapshot


def enrich_lead(lead: dict, *, force: bool = False, include_people: bool = False) -> dict:
    """
    Enrich a lead with Firecrawl + Apollo data.

    Args:
        lead:  Prospect dict (mutated in place and returned).
        force: If True, re-enrich even when enriched_at is already set.

    Returns the mutated lead dict.
    """
    if lead.get("enriched_at") and not force and not include_people:
        return lead

    website = (lead.get("website") or "").strip()
    lead.setdefault("contact_candidates", [])
    lead.setdefault("linkedin_candidates", [])
    lead.setdefault("enrichment_status", {})
    lead.setdefault("enrichment_snapshot_refs", [])

    # --- Firecrawl ---
    if website:
        fc_errors = []
        try:
            from sources.firecrawl import scrape_website
            fc = scrape_website(website, lead_id=lead.get("id", ""))
            if fc:
                lead["website_summary"]    = fc.get("website_summary") or lead.get("website_summary")
                lead["brand_signals"]      = fc.get("brand_signals")   or lead.get("brand_signals")
                # Always update the full list; only set the primary if not already present
                if fc.get("contact_page_emails"):
                    lead["contact_page_emails"] = fc["contact_page_emails"]
                if fc.get("contact_page_email") and not lead.get("contact_page_email"):
                    lead["contact_page_email"] = fc["contact_page_email"]
                if fc.get("contact_candidates"):
                    lead["contact_candidates"] = merge_contact_candidates(lead, fc["contact_candidates"])
                if fc.get("linkedin_candidates"):
                    lead["linkedin_candidates"] = merge_linkedin_candidates(lead, fc["linkedin_candidates"])
                fc_errors = fc.get("firecrawl_errors") or []
                snapshot_ref = save_provider_snapshot(
                    lead_id=lead.get("id", ""),
                    provider="firecrawl",
                    endpoint="scrape",
                    request_ref=website,
                    normalized={
                        "website_summary": lead.get("website_summary"),
                        "brand_signals": lead.get("brand_signals"),
                        "contact_page_emails": lead.get("contact_page_emails", []),
                        "social_links": fc.get("firecrawl_social_links", []),
                    },
                    raw={"pages": fc.get("firecrawl_pages", [])},
                    errors=fc_errors,
                )
                lead["enrichment_snapshot_refs"].append(snapshot_ref)
                lead["enrichment_status"]["firecrawl"] = {
                    "status": "partial" if fc_errors else "complete",
                    "last_run_at": datetime.now(timezone.utc).isoformat(),
                    "pages_scraped": len(fc.get("firecrawl_pages", [])),
                    "emails_found": len(fc.get("contact_page_emails", [])),
                    "social_links_found": len(fc.get("firecrawl_social_links", [])),
                    "errors": fc_errors[:5],
                }
            else:
                lead["enrichment_status"]["firecrawl"] = {
                    "status": "missing",
                    "last_run_at": datetime.now(timezone.utc).isoformat(),
                    "pages_scraped": 0,
                    "emails_found": 0,
                    "social_links_found": 0,
                    "errors": ["No Firecrawl data returned"],
                }
        except Exception as e:
            print(f"[enrich] Firecrawl error for {lead.get('name')}: {e}")
            lead["enrichment_status"]["firecrawl"] = {
                "status": "error",
                "last_run_at": datetime.now(timezone.utc).isoformat(),
                "pages_scraped": 0,
                "emails_found": 0,
                "social_links_found": 0,
                "errors": [str(e)],
            }

    # --- Apollo ---
    if website:
        try:
            from sources.apollo import enrich_organization
            ap = enrich_organization(website, lead_id=lead.get("id", ""))
            if ap:
                raw = ap.pop("apollo_organization_raw", None)
                for field in (
                    "apollo_organization_id",
                    "company_size", "industry_apollo", "founded_year",
                    "estimated_revenue", "apollo_keywords", "apollo_linkedin_url",
                ):
                    val = ap.get(field)
                    if val is not None:
                        lead[field] = val
                if ap.get("apollo_linkedin_url"):
                    lead["linkedin_candidates"] = merge_linkedin_candidates(lead, [{
                        "kind": "company",
                        "name": lead.get("name", ""),
                        "title": "Company page",
                        "url": ap["apollo_linkedin_url"],
                        "source_provider": "apollo",
                        "confidence": "high",
                        "selected": False,
                    }])
                fields = [k for k in ap if ap.get(k) not in (None, "", [])]
                snapshot_ref = save_provider_snapshot(
                    lead_id=lead.get("id", ""),
                    provider="apollo",
                    endpoint="organization_enrich",
                    request_ref=website,
                    normalized={k: ap.get(k) for k in fields},
                    raw=raw,
                    errors=[],
                )
                lead["enrichment_snapshot_refs"].append(snapshot_ref)
                lead["enrichment_status"]["apollo_organization"] = {
                    "status": "complete" if fields else "missing",
                    "last_run_at": datetime.now(timezone.utc).isoformat(),
                    "fields_returned": fields,
                    "errors": [],
                }
            else:
                lead["enrichment_status"]["apollo_organization"] = {
                    "status": "missing",
                    "last_run_at": datetime.now(timezone.utc).isoformat(),
                    "fields_returned": [],
                    "errors": ["No Apollo organization data returned"],
                }
        except Exception as e:
            print(f"[enrich] Apollo error for {lead.get('name')}: {e}")
            lead["enrichment_status"]["apollo_organization"] = {
                "status": "error",
                "last_run_at": datetime.now(timezone.utc).isoformat(),
                "fields_returned": [],
                "errors": [str(e)],
            }

    # --- Apollo People (controlled, only when explicitly requested) ---
    if include_people:
        try:
            from sources.apollo import enrich_person
            person = enrich_person(
                website=website,
                email=lead.get("contact_email") or lead.get("contact_page_email") or "",
                name=lead.get("decision_maker", ""),
                linkedin_url=lead.get("linkedin_url", ""),
                lead_id=lead.get("id", ""),
                run_waterfall_email=False,
            )
            raw = person.pop("apollo_person_raw", None) if person else None
            waterfall = person.pop("apollo_waterfall", None) if person else None
            if person and (person.get("name") or person.get("linkedin_url") or person.get("email")):
                if person.get("name") and not lead.get("decision_maker"):
                    lead["decision_maker"] = person["name"]
                if person.get("title") and not lead.get("decision_maker_title"):
                    lead["decision_maker_title"] = person["title"]
                if person.get("email") and is_valid_email(person["email"]) and not lead.get("contact_email"):
                    lead["contact_email"] = person["email"].lower()
                if person.get("email") and is_valid_email(person["email"]):
                    lead["contact_candidates"] = merge_contact_candidates(lead, [{
                        "email": person["email"],
                        "value": person["email"],
                        "source_provider": "apollo_people",
                        "source_url": "people_match",
                        "confidence": "medium" if not person.get("email_status") else str(person.get("email_status")),
                        "selected": False,
                    }])
                if person.get("linkedin_url"):
                    lead["linkedin_url"] = lead.get("linkedin_url") or person["linkedin_url"]
                    lead["linkedin_candidates"] = merge_linkedin_candidates(lead, [{
                        "kind": "person",
                        "name": person.get("name", ""),
                        "title": person.get("title", ""),
                        "url": person["linkedin_url"],
                        "source_provider": "apollo_people",
                        "confidence": "medium",
                        "selected": False,
                    }])
                snapshot_ref = save_provider_snapshot(
                    lead_id=lead.get("id", ""),
                    provider="apollo",
                    endpoint="people_match",
                    request_ref=website,
                    normalized=person,
                    raw={"person": raw, "waterfall": waterfall},
                    errors=[],
                )
                lead["enrichment_snapshot_refs"].append(snapshot_ref)
                lead["enrichment_status"]["apollo_people"] = {
                    "status": "partial",
                    "last_run_at": datetime.now(timezone.utc).isoformat(),
                    "fields_returned": [k for k, v in person.items() if v],
                    "errors": [],
                }
            else:
                lead["enrichment_status"]["apollo_people"] = {
                    "status": "missing",
                    "last_run_at": datetime.now(timezone.utc).isoformat(),
                    "fields_returned": [],
                    "errors": ["No Apollo person match. Add a decision-maker name, email, or LinkedIn URL first."],
                }
        except Exception as e:
            print(f"[enrich] Apollo people error for {lead.get('name')}: {e}")
            lead["enrichment_status"]["apollo_people"] = {
                "status": "error",
                "last_run_at": datetime.now(timezone.utc).isoformat(),
                "fields_returned": [],
                "errors": [str(e)],
            }

    lead["enriched_at"] = datetime.now(timezone.utc).isoformat()
    sync_selected_candidates(lead)
    lead["enrichment_audit"] = audit_lead(lead)
    _set_enrichment_health(lead)
    return lead


def _set_enrichment_health(lead: dict) -> None:
    """Roll per-provider enrichment_status into one top-level flag for the UI.

    health: "ok" | "partial" | "failed". "failed" means we got essentially
    nothing usable (no website summary, no email, no Apollo data), so the lead
    is a likely dud and should be visibly flagged rather than silently kept.
    """
    statuses = lead.get("enrichment_status", {}) or {}
    provider_states = [v.get("status") for v in statuses.values() if isinstance(v, dict)]
    errored = [v for v in statuses.values()
               if isinstance(v, dict) and v.get("status") == "error"]

    has_summary = bool((lead.get("website_summary") or "").strip())
    has_email = bool((lead.get("contact_page_email") or "").strip()
                     or lead.get("contact_page_emails")
                     or (lead.get("contact_email") or "").strip())
    has_apollo = bool(lead.get("company_size") or lead.get("industry_apollo")
                      or lead.get("founded_year") or lead.get("estimated_revenue"))

    if not (lead.get("website") or "").strip():
        health = "no_website"
    elif not has_summary and not has_email and not has_apollo:
        health = "failed"
    elif errored or not has_summary or not has_email or "partial" in provider_states or "missing" in provider_states:
        health = "partial"
    else:
        health = "ok"

    lead["enrichment_health"] = health
    lead["enrichment_failed"] = health == "failed"
