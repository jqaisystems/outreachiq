"""
OutreachIQ - Flask Server
Serves the dashboard and exposes a JSON API for lead management and outreach.
Run:  python server.py   ->   http://localhost:5001
"""

import csv
import glob
import io
import json
import os
import re
import shutil
import sys
import threading
import time
from collections import Counter, defaultdict

# Force UTF-8 console output on Windows. reconfigure() keeps the original
# stream objects intact (rewrapping .buffer breaks pytest's output capture).
if sys.platform == "win32":
    for _stream in (sys.stdout, sys.stderr):
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass

from datetime import datetime, date, timezone
from flask import Flask, jsonify, request, render_template, Response

from config import (
    DATA_DIR, PROSPECTS_JSON, EXPORTS_DIR, EMAILS_DIR, ENRICHMENT_DIR,
    ICP_RECOMMENDATIONS_JSON, INDUSTRY_QUERIES, INDUSTRY_LABELS,
    SERVICE_FOCUS_LABELS, SERVICE_OFFER_LABELS, SERVICE_MIX_LABELS,
    SEARCH_MODE_LABELS, MARKET_PRESETS,
    SERVICE_SEARCH_PRESETS, DEFAULT_LIMIT, MAX_LIMIT,
    GOOGLE_PLACES_API_KEY, FIRECRAWL_API_KEY, validate_keys,
    EMAIL_LOG_MD, DO_NOT_CONTACT_JSON, SEND_LOCK_JSON, SEND_COUNTER_JSON,
    SEND_ACTIVE_JSON,
    EMAIL_SIGNATURE, SEND_DELAY_SECONDS, DAILY_SEND_CAP, FOLLOW_UP_DAYS,
    REPLY_POLL_MINUTES, MEMORY_MD,
)
from enrich.audit import (
    audit_lead, audit_many, merge_contact_candidates,
    merge_linkedin_candidates, promote_best_contact_email, sync_selected_candidates,
)
from enrich.pipeline import enrich_lead
from enrich.tracking import log_api_usage, read_usage_summary
from email_repair import repair_written_entry
from email_tone import audit_email_tone, audit_many_email_tones, phrase_counts_for_leads, lint_ai_addon

app = Flask(__name__, static_folder="static", template_folder="templates")


# ---------------------------------------------------------------------------
# JSON database helpers
# ---------------------------------------------------------------------------

def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _today() -> str:
    return date.today().isoformat()


def _estimate_tokens_from_text(text: str) -> int:
    # Rough local estimate for manual Codex/Claude workflow. Exact tokens require direct model API usage.
    return max(1, int(len(text or "") / 4))


def _snapshot_records_for_lead(lead: dict) -> list[dict]:
    """Return safe, referenced snapshot metadata for a lead."""
    records = []
    base_dir = os.path.realpath(ENRICHMENT_DIR)
    refs = lead.get("enrichment_snapshot_refs") or []
    seen_ids = set()
    for ref in refs:
        path = os.path.realpath(str(ref))
        snapshot_id = os.path.basename(path)
        if not snapshot_id or snapshot_id in seen_ids:
            continue
        if not path.startswith(base_dir + os.sep):
            continue
        if not os.path.exists(path) or not os.path.isfile(path):
            continue
        try:
            with open(path, "r", encoding="utf-8-sig") as f:
                payload = json.load(f)
        except Exception as e:
            payload = {
                "timestamp": "",
                "provider": "unknown",
                "endpoint": "unknown",
                "request_ref": "",
                "errors": [f"Could not read snapshot: {e}"],
            }
        stat = os.stat(path)
        records.append({
            "id": snapshot_id,
            "provider": payload.get("provider", "unknown"),
            "endpoint": payload.get("endpoint", "unknown"),
            "timestamp": payload.get("timestamp", ""),
            "request_ref": payload.get("request_ref", ""),
            "errors": payload.get("errors", []),
            "size": stat.st_size,
            "modified_at": datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(),
        })
        seen_ids.add(snapshot_id)
    return sorted(records, key=lambda r: r.get("timestamp") or r.get("modified_at") or "", reverse=True)


def _snapshot_path_for_lead(lead: dict, snapshot_id: str) -> str | None:
    """Resolve a snapshot ID only if it is explicitly referenced by this lead."""
    requested = os.path.basename(snapshot_id or "")
    if not requested or requested != snapshot_id:
        return None
    base_dir = os.path.realpath(ENRICHMENT_DIR)
    for ref in lead.get("enrichment_snapshot_refs") or []:
        path = os.path.realpath(str(ref))
        if os.path.basename(path) != requested:
            continue
        if not path.startswith(base_dir + os.sep):
            return None
        if os.path.exists(path) and os.path.isfile(path):
            return path
    return None


def _coerce_prospects(data):
    """Normalise a parsed JSON value into a flat prospect list, or None."""
    if isinstance(data, list):
        return data
    if isinstance(data, dict) and "prospects" in data:
        return data["prospects"]
    return None


def _parse_prospects_text(text: str):
    """Parse prospects JSON text. On trailing-garbage corruption (the OneDrive
    sync signature), retry against the substring up to the last valid array.
    Returns a list, or None if nothing usable can be salvaged."""
    try:
        return _coerce_prospects(json.loads(text))
    except json.JSONDecodeError:
        pass
    end = text.rfind("]")
    while end != -1:
        try:
            salvaged = _coerce_prospects(json.loads(text[: end + 1]))
        except json.JSONDecodeError:
            salvaged = None
        if salvaged is not None:
            return salvaged
        end = text.rfind("]", 0, end)
    return None


def _load() -> list:
    """Load prospects.json as a flat list, self-healing on corruption.

    OneDrive sync conflicts can leave stale bytes after the closing ']', which
    makes a plain json.load raise and would otherwise 500 every API call. So we
    (1) try a normal parse, (2) try truncating to the last valid array and
    rewrite the repaired file, (3) fall back to the newest good backup. The
    dashboard stays up instead of going dark."""
    if not os.path.exists(PROSPECTS_JSON):
        return []

    with open(PROSPECTS_JSON, "r", encoding="utf-8") as f:
        text = f.read()
    try:
        data = _coerce_prospects(json.loads(text))
        if data is not None:
            return data
    except json.JSONDecodeError:
        data = None

    # Corrupt file: attempt in-place repair by truncating trailing garbage.
    print(f"WARNING: {PROSPECTS_JSON} is corrupt, attempting recovery...")
    repaired = _parse_prospects_text(text)
    if repaired is not None:
        print(f"  recovered {len(repaired)} leads by truncating trailing garbage; rewriting file.")
        _save(repaired)
        return repaired

    # Last resort: restore from the newest backup that parses.
    backups = sorted(glob.glob(os.path.join(BACKUPS_DIR, "prospects-*.json")), reverse=True)
    for bk in backups:
        try:
            with open(bk, "r", encoding="utf-8") as f:
                restored = _coerce_prospects(json.load(f))
        except (json.JSONDecodeError, OSError):
            restored = None
        if restored:
            print(f"  restored {len(restored)} leads from backup {os.path.basename(bk)}; rewriting file.")
            _save(restored)
            return restored

    print("  ERROR: no usable data or backup found. Returning empty list.")
    return []


BACKUPS_DIR = os.path.join(DATA_DIR, "backups")
MAX_BACKUPS = 10


def _rotate_backups() -> None:
    """Keep only the most recent MAX_BACKUPS prospects backups."""
    backups = sorted(glob.glob(os.path.join(BACKUPS_DIR, "prospects-*.json")))
    for old in backups[:-MAX_BACKUPS]:
        try:
            os.remove(old)
        except OSError:
            pass


def _save(prospects: list) -> None:
    """Atomically write prospects.json with a rolling backup.

    Writes to a temp file then os.replace() (atomic on Windows), so a crash or
    OneDrive sync conflict mid-write cannot truncate the live database. The
    previous file is copied into data/backups/ first.
    """
    os.makedirs(DATA_DIR, exist_ok=True)
    for p in prospects:
        sync_selected_candidates(p)

    # Back up the current good file before overwriting it.
    if os.path.exists(PROSPECTS_JSON):
        os.makedirs(BACKUPS_DIR, exist_ok=True)
        stamp = _now().replace(":", "-").replace(".", "-")
        try:
            shutil.copy2(PROSPECTS_JSON, os.path.join(BACKUPS_DIR, f"prospects-{stamp}.json"))
            _rotate_backups()
        except OSError:
            pass  # never let backup failure block the save

    tmp_path = PROSPECTS_JSON + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(prospects, f, indent=2, ensure_ascii=False)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp_path, PROSPECTS_JSON)


def _find(prospects: list, lead_id: str):
    for p in prospects:
        if p["id"] == lead_id:
            return p
    return None


def _truthy(value) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() in ("1", "true", "yes", "on")


def _normalize_choice(value: str | None, valid: dict, default: str) -> str:
    key = str(value or "").strip()
    return key if key in valid else default


def _service_label(service_focus: str) -> str:
    return SERVICE_FOCUS_LABELS.get(service_focus, SERVICE_FOCUS_LABELS["branding"])


def _offer_label(service_key: str) -> str:
    return SERVICE_OFFER_LABELS.get(service_key, SERVICE_OFFER_LABELS["branding"])


def _mix_label(service_mix: str) -> str:
    return SERVICE_MIX_LABELS.get(service_mix, SERVICE_MIX_LABELS["smart_mix"])


def _mode_label(search_mode: str) -> str:
    return SEARCH_MODE_LABELS.get(search_mode, SEARCH_MODE_LABELS["direct_client"])


def _dedupe_services(services: list[str], primary_service: str) -> list[str]:
    seen = set()
    normalized = []
    for service in services:
        key = _normalize_choice(service, SERVICE_OFFER_LABELS, "")
        if not key or key == primary_service or key in seen:
            continue
        seen.add(key)
        normalized.append(key)
    return normalized


def _lead_text_for_mix(*, industry: str = "", query: str = "", lead: dict | None = None) -> str:
    lead = lead or {}
    keyword_text = " ".join(str(k or "") for k in (lead.get("apollo_keywords") or []))
    parts = [
        industry,
        query,
        lead.get("industry", ""),
        lead.get("niche", ""),
        lead.get("name", ""),
        lead.get("website_summary", ""),
        lead.get("brand_signals", ""),
        lead.get("industry_apollo", ""),
        keyword_text,
    ]
    return " ".join(str(part or "") for part in parts).lower()


def _secondary_services_for(
    *,
    service_mix: str,
    service_focus: str,
    search_mode: str,
    industry: str = "",
    query: str = "",
    lead: dict | None = None,
) -> list[str]:
    primary = _normalize_choice(service_focus, SERVICE_OFFER_LABELS, "branding")
    mix = _normalize_choice(service_mix, SERVICE_MIX_LABELS, "smart_mix")

    fixed = {
        "branding_only": ["branding"],
        "branding_web": ["branding", "web_design"],
        "branding_web_print": ["branding", "web_design", "editorial_print"],
        "all_services": ["branding", "web_design", "editorial_print", "ai_systems"],
    }
    if mix in fixed:
        return _dedupe_services(fixed[mix], primary)

    text = _lead_text_for_mix(industry=industry, query=query, lead=lead)
    content_heavy = any(term in text for term in (
        "content", "social media", "ecommerce", "e-commerce", "shopify", "catalog",
        "automation", "operations", "production", "newsletter", "creator"
    ))
    industry_key = (industry or (lead or {}).get("industry") or (lead or {}).get("source_industry") or "").lower()
    query_key = (query or (lead or {}).get("search_query") or "").lower()

    if search_mode == "agency_partner" or _truthy((lead or {}).get("partner_lane")):
        services = ["branding", "web_design"]
        if content_heavy:
            services.append("ai_systems")
        return _dedupe_services(services, primary)

    construction_print = (
        industry_key in ("construction", "real_estate", "architecture")
        or any(term in query_key for term in ("construction", "real estate", "developer", "architecture", "interior"))
    )
    hospitality_web = (
        industry_key in ("hospitality", "luxury", "beauty", "health")
        or any(term in query_key for term in ("hospitality", "hotel", "restaurant", "luxury", "beauty", "wellness", "clinic"))
    )
    tech_ai = (
        industry_key in ("tech",)
        or any(term in query_key for term in ("tech", "saas", "ecommerce", "e-commerce", "content", "automation"))
        or content_heavy
    )

    if construction_print:
        return _dedupe_services(["branding", "web_design", "editorial_print"], primary)
    if hospitality_web:
        return _dedupe_services(["branding", "web_design"], primary)
    if tech_ai:
        return _dedupe_services(["branding", "ai_systems"], primary)
    if primary in ("web_design", "editorial_print", "ai_systems"):
        return _dedupe_services(["branding"], primary)
    return []


def _secondary_service_labels(services: list[str]) -> list[str]:
    return [_offer_label(service) for service in services]


def _outreach_angle_for(
    *,
    primary_service: str,
    secondary_services: list[str],
    search_mode: str,
    partner_lane: bool = False,
    service_mix: str = "smart_mix",
) -> str:
    secondary = set(secondary_services or [])
    if search_mode == "agency_partner" or partner_lane:
        if "ai_systems" in secondary or primary_service == "ai_systems":
            return "Agency overflow support for identity, web design, and selective AI systems."
        return "Agency overflow support for identity and web design."
    if "ai_systems" in secondary or primary_service == "ai_systems":
        return "Brand-led AI systems for content-heavy operations."
    if "editorial_print" in secondary:
        return "Brand identity with supporting website and proposal materials."
    if "web_design" in secondary:
        return "Brand identity with supporting website direction."
    if primary_service == "web_design":
        return "Design-led website opportunity with brand identity support."
    if primary_service == "editorial_print":
        return "Editorial and print materials supported by brand identity."
    return "Focused brand identity opportunity."


def _service_guidance(primary_service: str, secondary_services: list[str], service_mix: str) -> str:
    supporting = ", ".join(_secondary_service_labels(secondary_services)) or "None"
    menu_note = (
        "All Services was selected, but keep the first email focused on one primary offer and at most one supporting service."
        if service_mix == "all_services"
        else "Do not list services like a menu. Mention one primary offer and at most one supporting service."
    )
    return f"Primary: {_offer_label(primary_service)}. Supporting: {supporting}. {menu_note}"


def _motion_focused(lead: dict) -> bool:
    terms = (
        "motion graphics", "motion design", "animation studio", "video production",
        "film production", "vfx", "3d animation", "explainer video"
    )
    text_parts = [
        lead.get("name", ""),
        lead.get("industry", ""),
        lead.get("niche", ""),
        lead.get("website_summary", ""),
        lead.get("brand_signals", ""),
        " ".join(lead.get("apollo_keywords") or []),
    ]
    text = " ".join(str(part or "") for part in text_parts).lower()
    return any(term in text for term in terms)


def _prospecting_context(data: dict, *, industry: str, query: str, location: str) -> dict:
    service_focus = _normalize_choice(
        data.get("service_focus"),
        SERVICE_FOCUS_LABELS,
        "branding",
    )
    search_mode = _normalize_choice(
        data.get("search_mode") or ("agency_partner" if _truthy(data.get("partner_lane")) else ""),
        SEARCH_MODE_LABELS,
        "direct_client",
    )
    market_preset = _normalize_choice(data.get("market_preset"), MARKET_PRESETS, "premium_global")
    partner_lane = search_mode == "agency_partner" or _truthy(data.get("partner_lane"))
    exclude_motion = _truthy(data.get("exclude_motion", True))
    service_mix = _normalize_choice(data.get("service_mix"), SERVICE_MIX_LABELS, "smart_mix")
    primary_service = _normalize_choice(data.get("primary_service") or service_focus, SERVICE_OFFER_LABELS, "branding")
    secondary_services = _secondary_services_for(
        service_mix=service_mix,
        service_focus=primary_service,
        search_mode=search_mode,
        industry=industry,
        query=query,
        lead=data,
    )
    outreach_angle = _outreach_angle_for(
        primary_service=primary_service,
        secondary_services=secondary_services,
        search_mode=search_mode,
        partner_lane=partner_lane,
        service_mix=service_mix,
    )
    return {
        "service_focus": service_focus,
        "service_focus_label": _service_label(service_focus),
        "service_mix": service_mix,
        "service_mix_label": _mix_label(service_mix),
        "primary_service": primary_service,
        "primary_service_label": _offer_label(primary_service),
        "secondary_services": secondary_services,
        "secondary_service_labels": _secondary_service_labels(secondary_services),
        "outreach_angle": outreach_angle,
        "search_mode": search_mode,
        "search_mode_label": _mode_label(search_mode),
        "market_preset": market_preset,
        "market_preset_label": MARKET_PRESETS[market_preset]["label"],
        "partner_lane": partner_lane,
        "exclude_motion": exclude_motion,
        "search_query": query,
        "search_location": location,
        "source_industry": industry,
    }


def _load_icp_recommendations() -> list[dict]:
    if os.path.exists(ICP_RECOMMENDATIONS_JSON):
        with open(ICP_RECOMMENDATIONS_JSON, "r", encoding="utf-8-sig") as f:
            data = json.load(f)
        if isinstance(data, list):
            return data

    fallback = []
    for service_focus, modes in SERVICE_SEARCH_PRESETS.items():
        for search_mode, presets in modes.items():
            default_location = MARKET_PRESETS["premium_global"]["default_locations"][0]
            for preset in presets[:2]:
                fallback.append({
                    "service_focus": service_focus,
                    "search_mode": search_mode,
                    "market_preset": "premium_global",
                    "query": preset["query"],
                    "location": default_location,
                    "reason": f"{preset['label']} fits {_service_label(service_focus).lower()} prospecting.",
                    "expected_fit": _mode_label(search_mode),
                })
    return fallback


def _safe_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).date()
    except ValueError:
        try:
            return date.fromisoformat(str(value)[:10])
        except ValueError:
            return None


def _lead_quality_counts(leads: list[dict]) -> dict:
    counts = Counter()
    for p in leads:
        priority = p.get("priority") or ""
        status = p.get("status") or ""
        if priority in ("hot", "warm", "cold"):
            counts[priority] += 1
        elif status == "skip":
            counts["skip"] += 1
        else:
            counts["unscored"] += 1
        if status in ("sent", "replied", "meeting", "converted"):
            counts["sent_or_later"] += 1
        if status in ("replied", "meeting", "converted"):
            counts["replied_or_later"] += 1
        if status in ("meeting", "converted"):
            counts["meeting_or_later"] += 1
    total = len(leads)
    hot_warm = counts["hot"] + counts["warm"]
    cold_skip = counts["cold"] + counts["skip"]
    return {
        "total": total,
        "hot": counts["hot"],
        "warm": counts["warm"],
        "cold": counts["cold"],
        "skip": counts["skip"],
        "unscored": counts["unscored"],
        "sent_or_later": counts["sent_or_later"],
        "replied_or_later": counts["replied_or_later"],
        "meeting_or_later": counts["meeting_or_later"],
        "hot_warm_rate": round(hot_warm / total, 3) if total else 0,
        "cold_skip_rate": round(cold_skip / total, 3) if total else 0,
        "reply_rate": round(counts["replied_or_later"] / counts["sent_or_later"], 3) if counts["sent_or_later"] else 0,
    }


def _monthly_prospecting_refresh(prospects: list[dict], *, days: int = 30) -> dict:
    ensured = [_ensure_fields(p) for p in prospects]
    today = date.today()
    cutoff = date.fromordinal(today.toordinal() - days)
    recent = [
        p for p in ensured
        if (_safe_date(p.get("date_added")) or _safe_date(p.get("found_at")) or today) >= cutoff
    ]
    basis = "last_30_days" if recent else "all_time"
    scoped = recent or ensured

    groups = defaultdict(list)
    for p in scoped:
        key = (
            p.get("service_focus") or "branding",
            p.get("search_mode") or "direct_client",
            p.get("niche") or p.get("industry") or "Unknown",
            p.get("region") or p.get("country") or "Unknown",
        )
        groups[key].append(p)

    rows = []
    for (service_focus, search_mode, niche, region), items in groups.items():
        quality = _lead_quality_counts(items)
        rows.append({
            "service_focus": service_focus,
            "service_focus_label": _service_label(service_focus),
            "search_mode": search_mode,
            "search_mode_label": _mode_label(search_mode),
            "niche": niche,
            "region": region,
            **quality,
        })

    rows.sort(key=lambda r: (r["hot_warm_rate"], r["reply_rate"], r["total"]), reverse=True)
    promote = [r for r in rows if r["total"] >= 3 and r["hot_warm_rate"] >= 0.45][:5]
    demote = sorted(
        [r for r in rows if r["total"] >= 3 and r["cold_skip_rate"] >= 0.65],
        key=lambda r: (r["cold_skip_rate"], r["total"]),
        reverse=True,
    )[:5]

    return {
        "generated_at": _now(),
        "window_days": days,
        "basis": basis,
        "summary": _lead_quality_counts(scoped),
        "groups": rows[:24],
        "promote": promote,
        "demote": demote,
    }


def _next_favorite_order(prospects: list[dict]) -> int:
    orders = []
    for p in prospects:
        try:
            orders.append(int(p.get("favorite_order") or 0))
        except (TypeError, ValueError):
            continue
    return (max(orders) if orders else 0) + 1


def _sort_leads(leads: list[dict], sort_by: str, order: str) -> None:
    reverse = order == "desc"
    if sort_by == "score":
        leads.sort(key=lambda p: p.get("score", 0) or 0, reverse=reverse)
    elif sort_by == "name":
        leads.sort(key=lambda p: p.get("name", "").lower(), reverse=reverse)
    elif sort_by == "rating":
        leads.sort(key=lambda p: p.get("rating", 0) or 0, reverse=reverse)
    elif sort_by in ("favorited_at", "favorite_order", "favorite"):
        leads.sort(
            key=lambda p: (
                int(p.get("favorite_order") or 0),
                p.get("favorited_at") or "",
            ),
            reverse=reverse,
        )
    else:
        leads.sort(key=lambda p: p.get("found_at", "") or "", reverse=reverse)


EMAIL_REVIEW_CODES = {
    "bad_greeting",
    "company_fragment_greeting",
    "generic_greeting",
    "missing_greeting",
    "old_single_draft",
    "weak_evidence",
    "over_80_words",
    "hard_cta",
    "missing_soft_cta",
    "portfolio_in_body",
    "hedge_phrase",
    "ai_overused",
    "ai_needs_fit",
    "render_artifact",
    "template_mismatch",
    "retired_phrase",
    "subject_template",
    "subject_truncated",
    "review_count_only",
    "clone_body",
}

SEND_GATE_BLOCKING_CODES = {
    "missing_contact_email",
    "bad_greeting",
    "company_fragment_greeting",
    "missing_greeting",
    # 2026-07-02 zero-replies diagnostic: objective generation defects that
    # must never reach a prospect (pipeline vocab, doubled merge clauses,
    # non-Latin leakage, truncated subjects, partner copy on direct clients).
    "render_artifact",
    "template_mismatch",
    "subject_truncated",
}


def _review_status_from_flags(flags: list[dict], fallback: str = "strong") -> str:
    if any(f.get("severity") == "risky" for f in flags):
        return "risky"
    if flags or fallback == "needs_review":
        return "needs_review"
    return fallback if fallback in ("strong", "needs_review", "risky") else "strong"


def _email_review_flags(lead: dict, tone_audit: dict) -> list[dict]:
    """Return the subset of local draft issues that matter before sending."""
    flags = []
    seen = set()

    if not (lead.get("contact_email") or "").strip():
        flags.append({
            "code": "missing_contact_email",
            "label": "Missing email",
            "severity": "risky",
            "count": 1,
            "detail": "Add a sendable contact email before outreach.",
        })
        seen.add("missing_contact_email")

    for flag in tone_audit.get("flags") or []:
        code = flag.get("code")
        if code not in EMAIL_REVIEW_CODES or code in seen:
            continue
        flags.append(flag)
        seen.add(code)

    return flags


def _send_gate_flags(lead: dict, prospects: list[dict], variant_index: int | None = None) -> tuple[dict, list[dict]]:
    audit = audit_email_tone(lead)
    flags = []
    seen = set()

    def add_flag(code: str, label: str, severity: str, detail: str = ""):
        if code in seen:
            return
        flags.append({
            "code": code,
            "label": label,
            "severity": severity,
            "count": 1,
            "detail": detail,
        })
        seen.add(code)

    if not (lead.get("contact_email") or "").strip():
        add_flag("missing_contact_email", "Missing email", "risky", "Add a sendable contact email before outreach.")

    source_flags = audit.get("flags") or []
    variant_checks = audit.get("variant_checks") or []
    if variant_index is not None and variant_checks:
        target_check = next(
            (check for check in variant_checks if int(check.get("index", -1)) == variant_index),
            variant_checks[variant_index] if 0 <= variant_index < len(variant_checks) else None,
        )
        if target_check:
            source_flags = target_check.get("flags") or []

    for flag in source_flags:
        code = flag.get("code")
        if code not in EMAIL_REVIEW_CODES or code in seen:
            continue
        flags.append(flag)
        seen.add(code)

    email = (lead.get("contact_email") or "").strip().lower()
    contacted_statuses = {"sent", "follow-up", "replied", "meeting", "converted"}
    if email:
        duplicates = [
            p for p in prospects
            if p.get("id") != lead.get("id")
            and (p.get("contact_email") or "").strip().lower() == email
            and p.get("status") in contacted_statuses
        ]
        if duplicates:
            names = ", ".join(p.get("name", "another lead") for p in duplicates[:3])
            add_flag("duplicate_contact_email", "Duplicate email", "needs_review", f"This email was already used for: {names}.")

    has_linkedin = bool(lead.get("linkedin_url")) or any(
        (profile.get("url") or profile.get("name"))
        for profile in (lead.get("linkedin_profiles") or [])
    )
    if lead.get("priority") in ("hot", "warm") and not has_linkedin:
        add_flag("missing_linkedin_warmup", "LinkedIn warmup missing", "needs_review", "High-value leads should be warmed up on LinkedIn before email when possible.")

    return audit, flags


def _variant_meta(lead: dict, variant_index: int | None) -> dict:
    variants = lead.get("email_variants") or []
    if variants:
        if variant_index is None or variant_index < 0 or variant_index >= len(variants):
            variant_index = 0
        variant = variants[variant_index]
        return {
            "index": variant_index,
            "label": variant.get("label") or chr(65 + variant_index),
            "approach": variant.get("approach") or variant.get("type") or "",
            "subject": variant.get("subject") or "",
        }
    return {
        "index": 0,
        "label": "single",
        "approach": "legacy",
        "subject": lead.get("outreach_subject", ""),
    }


def _record_send_prepared(lead: dict, variant_index: int | None, channel: str) -> None:
    meta = _variant_meta(lead, variant_index)
    lead["last_send_prepared_at"] = _now()
    lead["last_send_channel"] = channel
    lead["last_send_variant_index"] = meta["index"]
    lead["last_send_variant_label"] = meta["label"]
    lead["last_send_variant_approach"] = meta["approach"]
    lead["last_send_subject"] = meta["subject"]


def _record_sent(lead: dict, variant_index: int | None = None, channel: str = "") -> None:
    if variant_index is None and lead.get("last_send_variant_index") is not None:
        try:
            variant_index = int(lead.get("last_send_variant_index"))
        except (TypeError, ValueError):
            variant_index = None
    channel = channel or lead.get("last_send_channel") or "manual"
    meta = _variant_meta(lead, variant_index)
    lead["variant_sent_index"] = meta["index"]
    lead["variant_sent_label"] = meta["label"]
    lead["variant_sent_approach"] = meta["approach"]
    lead["variant_sent_subject"] = meta["subject"]
    lead["send_channel"] = channel
    lead["sent_recorded_at"] = _now()
    if not lead.get("date_sent"):
        lead["date_sent"] = _today()


def _record_reply(lead: dict, reply_type: str = "", reply_notes: str = "") -> None:
    lead["reply_type"] = reply_type
    lead["reply_notes"] = reply_notes
    lead["date_replied"] = _today()
    lead["reply_recorded_at"] = _now()


def _clear_sent_record(lead: dict) -> None:
    for key in (
        "date_sent",
        "variant_sent_index",
        "variant_sent_label",
        "variant_sent_approach",
        "variant_sent_subject",
        "send_channel",
        "sent_recorded_at",
    ):
        lead[key] = None if key in ("date_sent", "variant_sent_index", "sent_recorded_at") else ""


def _ensure_fields(p: dict) -> dict:
    """Backfill any missing fields introduced in OutreachIQ."""
    defaults = {
        "linkedin_owner":   "",
        "email_path":       None,
        "date_added":       p.get("found_at", _today())[:10] if p.get("found_at") else _today(),
        "date_scored":      None,
        "date_sent":        None,
        "date_replied":     None,
        "notes":            "",
        "is_favorite":      _truthy(p.get("is_favorite", p.get("favorite", False))),
        "favorite_note":    p.get("favorite_note", "") or "",
        "favorited_at":     p.get("favorited_at"),
        "favorite_order":   p.get("favorite_order"),
        # Prospecting context
        "service_focus":    p.get("service_focus", "branding"),
        "service_focus_label": p.get("service_focus_label", SERVICE_FOCUS_LABELS["branding"]),
        "service_mix":      p.get("service_mix", "smart_mix"),
        "service_mix_label": p.get("service_mix_label", SERVICE_MIX_LABELS["smart_mix"]),
        "primary_service":  p.get("primary_service", p.get("service_focus", "branding")),
        "primary_service_label": p.get("primary_service_label", SERVICE_OFFER_LABELS["branding"]),
        "secondary_services": p.get("secondary_services", []),
        "secondary_service_labels": p.get("secondary_service_labels", []),
        "outreach_angle":   p.get("outreach_angle", ""),
        "search_mode":      p.get("search_mode", "agency_partner" if p.get("industry") in ("agency", "branding") else "direct_client"),
        "search_mode_label": p.get("search_mode_label", ""),
        "market_preset":    p.get("market_preset", "premium_global"),
        "market_preset_label": p.get("market_preset_label", MARKET_PRESETS["premium_global"]["label"]),
        "partner_lane":     _truthy(p.get("partner_lane", p.get("industry") in ("agency", "branding"))),
        "exclude_motion":   _truthy(p.get("exclude_motion", True)),
        "search_query":     p.get("search_query", ""),
        "search_location":  p.get("search_location", ""),
        "source_industry":  p.get("source_industry", p.get("industry", "")),
        "score":            p.get("score", 0) or 0,
        "priority":         p.get("priority", "") or "",
        "score_reason":     p.get("score_reason", "") or "",
        "brand_gap":        p.get("brand_gap", "") or "",
        "outreach_subject": p.get("outreach_subject", "") or "",
        "outreach_draft":   p.get("outreach_draft", "") or "",
        "linkedin_note":    p.get("linkedin_note", "") or "",
        "contact_email":    p.get("contact_email", "") or "",
        "linkedin_url":     p.get("linkedin_url", "") or "",
        "decision_maker":   p.get("decision_maker", "") or "",
        "linkedin_profiles": p.get("linkedin_profiles", []),
        # Email variants (v4) + legacy sequence support
        "email_variants":      p.get("email_variants", p.get("email_sequence", [])),
        "trigger":             p.get("trigger", ""),
        # Optional AI add-on (a P.S. that rides along with the branding email)
        "ai_addon":            p.get("ai_addon", "") or "",
        # On by default: the add-on rides along unless the operator explicitly removes it
        # (an explicit False is stored on the lead and persists).
        "ai_addon_enabled":    _truthy(p.get("ai_addon_enabled", True)),
        "tone_audit":          p.get("tone_audit", {}),
        "last_send_prepared_at": p.get("last_send_prepared_at"),
        "last_send_channel": p.get("last_send_channel", ""),
        "last_send_variant_index": p.get("last_send_variant_index"),
        "last_send_variant_label": p.get("last_send_variant_label", ""),
        "last_send_variant_approach": p.get("last_send_variant_approach", ""),
        "last_send_subject": p.get("last_send_subject", ""),
        "variant_sent_index": p.get("variant_sent_index"),
        "variant_sent_label": p.get("variant_sent_label", ""),
        "variant_sent_approach": p.get("variant_sent_approach", ""),
        "variant_sent_subject": p.get("variant_sent_subject", ""),
        "send_channel": p.get("send_channel", ""),
        "sent_recorded_at": p.get("sent_recorded_at"),
        "reply_type": p.get("reply_type", ""),
        "reply_notes": p.get("reply_notes", ""),
        "reply_recorded_at": p.get("reply_recorded_at"),
        # Enrichment fields (Firecrawl + Apollo)
        "enriched_at":        p.get("enriched_at"),
        "website_summary":    p.get("website_summary"),
        "brand_signals":      p.get("brand_signals"),
        "contact_page_email": p.get("contact_page_email", ""),
        "company_size":       p.get("company_size"),
        "industry_apollo":    p.get("industry_apollo"),
        "founded_year":       p.get("founded_year"),
        "estimated_revenue":  p.get("estimated_revenue"),
        "apollo_keywords":    p.get("apollo_keywords", []),
        "apollo_linkedin_url":  p.get("apollo_linkedin_url", ""),
        "contact_page_emails":  p.get("contact_page_emails", []),
        "apollo_organization_id": p.get("apollo_organization_id", ""),
        "contact_candidates": p.get("contact_candidates", []),
        "linkedin_candidates": p.get("linkedin_candidates", []),
        "enrichment_status": p.get("enrichment_status", {}),
        "enrichment_audit": p.get("enrichment_audit", {}),
        "enrichment_snapshot_refs": p.get("enrichment_snapshot_refs", []),
        "enrichment_health": p.get("enrichment_health", ""),
        "enrichment_failed": _truthy(p.get("enrichment_failed", False)),
        # Gmail sending + approval (Part 2/4)
        "approved_variant": p.get("approved_variant"),
        "approved_at": p.get("approved_at"),
        "gmail_message_id": p.get("gmail_message_id", ""),
        "gmail_thread_id": p.get("gmail_thread_id", ""),
        "send_blocked_reason": p.get("send_blocked_reason", ""),
        "reply_snippet": p.get("reply_snippet", ""),
        "reply_from": p.get("reply_from", ""),
        "reply_received_at": p.get("reply_received_at"),
        "follow_up_count": p.get("follow_up_count", 0) or 0,
    }
    for key, val in defaults.items():
        if key not in p:
            p[key] = val
    p["service_focus"] = _normalize_choice(p.get("service_focus"), SERVICE_FOCUS_LABELS, "branding")
    p["service_focus_label"] = _service_label(p["service_focus"])
    p["search_mode"] = _normalize_choice(
        p.get("search_mode") or ("agency_partner" if _truthy(p.get("partner_lane")) else ""),
        SEARCH_MODE_LABELS,
        "direct_client",
    )
    p["search_mode_label"] = _mode_label(p["search_mode"])
    p["market_preset"] = _normalize_choice(p.get("market_preset"), MARKET_PRESETS, "premium_global")
    p["market_preset_label"] = MARKET_PRESETS[p["market_preset"]]["label"]
    p["partner_lane"] = p["search_mode"] == "agency_partner" or _truthy(p.get("partner_lane"))
    p["exclude_motion"] = _truthy(p.get("exclude_motion", True))
    p["service_mix"] = _normalize_choice(p.get("service_mix"), SERVICE_MIX_LABELS, "smart_mix")
    p["service_mix_label"] = _mix_label(p["service_mix"])
    p["primary_service"] = _normalize_choice(p.get("primary_service") or p["service_focus"], SERVICE_OFFER_LABELS, "branding")
    p["primary_service_label"] = _offer_label(p["primary_service"])
    p["secondary_services"] = _secondary_services_for(
        service_mix=p["service_mix"],
        service_focus=p["primary_service"],
        search_mode=p["search_mode"],
        industry=p.get("source_industry") or p.get("industry", ""),
        query=p.get("search_query", ""),
        lead=p,
    )
    p["secondary_service_labels"] = _secondary_service_labels(p["secondary_services"])
    p["outreach_angle"] = _outreach_angle_for(
        primary_service=p["primary_service"],
        secondary_services=p["secondary_services"],
        search_mode=p["search_mode"],
        partner_lane=p["partner_lane"],
        service_mix=p["service_mix"],
    )
    # Normalize status: map legacy statuses to new lifecycle
    status_map = {
        "new":       "unscored",
        "scored":    p.get("priority", "cold") if p.get("priority") else "unscored",
        "approved":  p.get("priority", "warm") if p.get("priority") else "warm",
        "contacted": "sent",
        "skipped":   "skip",
    }
    if p.get("status") in status_map and p.get("status") not in (
        "unscored", "hot", "warm", "cold", "skip", "drafted", "sent", "replied", "meeting", "converted"
    ):
        p["status"] = status_map[p["status"]]
    # Migrate legacy single linkedin fields into linkedin_profiles array
    if not p.get("linkedin_profiles"):
        legacy_url = p.get("linkedin_url", "") or ""
        legacy_note = p.get("linkedin_note", "") or ""
        legacy_owner = p.get("linkedin_owner", "") or p.get("decision_maker", "") or ""
        legacy_title = p.get("decision_maker_title", "") or ""
        if legacy_url or legacy_note or legacy_owner:
            p["linkedin_profiles"] = [{
                "name": legacy_owner,
                "title": legacy_title,
                "url": legacy_url,
                "note": legacy_note,
            }]
        else:
            p["linkedin_profiles"] = []

    contact_seed = []
    for email in [p.get("contact_email"), p.get("contact_page_email"), *(p.get("contact_page_emails") or [])]:
        if email:
            contact_seed.append({
                "email": email,
                "value": email,
                "source_provider": "existing" if email == p.get("contact_email") else "firecrawl",
                "source_url": p.get("website", ""),
                "confidence": "high" if email == p.get("contact_email") else "medium",
                "selected": False,
            })
    p["contact_candidates"] = merge_contact_candidates(p, contact_seed)

    linkedin_seed = []
    if p.get("apollo_linkedin_url"):
        linkedin_seed.append({
            "kind": "company",
            "name": p.get("name", ""),
            "title": "Company page",
            "url": p.get("apollo_linkedin_url"),
            "source_provider": "apollo",
            "confidence": "high",
            "selected": False,
        })
    if p.get("linkedin_url"):
        linkedin_seed.append({
            "kind": "person",
            "name": p.get("decision_maker", ""),
            "title": p.get("decision_maker_title", ""),
            "url": p.get("linkedin_url"),
            "source_provider": "existing",
            "confidence": "medium",
            "selected": False,
        })
    p["linkedin_candidates"] = merge_linkedin_candidates(p, linkedin_seed)
    sync_selected_candidates(p)
    p["enrichment_audit"] = audit_lead(p)
    if (p.get("email_variants") or p.get("outreach_draft")) and not p.get("tone_audit"):
        p["tone_audit"] = audit_email_tone(p)
    return p


# ---------------------------------------------------------------------------
# Pages
# ---------------------------------------------------------------------------

@app.route("/")
def index():
    return render_template("index.html")


# ---------------------------------------------------------------------------
# API: Stats
# ---------------------------------------------------------------------------

@app.route("/api/stats")
def api_stats():
    prospects = _load()
    ensured = [_ensure_fields(p) for p in prospects]
    enrichment = audit_many(ensured)
    stats = {
        "total":     len(prospects),
        "unscored":  sum(1 for p in prospects if p.get("status") == "unscored"),
        "hot":       sum(1 for p in prospects if p.get("priority") == "hot"),
        "warm":      sum(1 for p in prospects if p.get("priority") == "warm"),
        "cold":      sum(1 for p in prospects if p.get("priority") == "cold"),
        "drafted":   sum(1 for p in prospects if p.get("status") == "drafted"),
        "sent":      sum(1 for p in prospects if p.get("status") == "sent"),
        "bounced":   sum(1 for p in prospects if p.get("status") == "bounced"),
        "follow_up": sum(1 for p in prospects if p.get("status") == "follow-up"),
        "replied":   sum(1 for p in prospects if p.get("status") == "replied"),
        "meeting":   sum(1 for p in prospects if p.get("status") == "meeting"),
        "converted": sum(1 for p in prospects if p.get("status") == "converted"),
        "skip":      sum(1 for p in prospects if p.get("status") == "skip"),
        "favorites": sum(1 for p in ensured if p.get("is_favorite")),
        "api_keys":  validate_keys(),
        "enrichment": enrichment["counts"],
        "enrichment_missing": enrichment["missing_counts"],
    }
    # Scored = unique leads with a priority or an explicit skip status.
    stats["scored"] = sum(
        1 for p in ensured
        if p.get("priority") in ("hot", "warm", "cold") or p.get("status") == "skip"
    )
    stats["variant_performance"] = _variant_performance(ensured)
    stats["sending"] = {
        "kill_switch": _kill_switch_on(),
        "sent_today": _send_count_today(),
        "daily_cap": DAILY_SEND_CAP,
        "approved_pending": sum(
            1 for p in ensured
            if _approved_index(p) is not None and p.get("status") != "sent"
        ),
        "followups_ready": sum(
            1 for p in ensured
            if p.get("status") == "sent" and (p.get("follow_up_body") or "").strip()
            and not (p.get("gmail_followup_message_id") or "").strip()
        ),
    }
    return jsonify(stats)


def _variant_performance(prospects: list[dict]) -> dict:
    """Reply rate per variant label (A/B/C) and per industry, among sent leads."""
    replied_statuses = {"replied", "meeting", "converted"}
    by_variant: dict[str, dict] = {}
    by_industry: dict[str, dict] = {}

    for p in prospects:
        if p.get("status") not in ({"sent", "follow-up"} | replied_statuses):
            continue
        if not p.get("date_sent") and p.get("status") == "sent":
            pass  # still counts as a send attempt
        replied = p.get("status") in replied_statuses
        label = (p.get("variant_sent_label") or "?").upper()
        vd = by_variant.setdefault(label, {"sent": 0, "replied": 0})
        vd["sent"] += 1
        vd["replied"] += int(replied)
        ind = p.get("source_industry") or p.get("industry") or "other"
        idd = by_industry.setdefault(ind, {"sent": 0, "replied": 0})
        idd["sent"] += 1
        idd["replied"] += int(replied)

    def with_rate(d):
        return {
            k: {**v, "reply_rate": round(100 * v["replied"] / v["sent"], 1) if v["sent"] else 0.0}
            for k, v in sorted(d.items())
        }

    return {"by_variant": with_rate(by_variant), "by_industry": with_rate(by_industry)}


@app.route("/api/prospecting/recommendations")
def api_prospecting_recommendations():
    prospects = _load()
    return jsonify({
        "services": [
            {"key": key, "label": label}
            for key, label in SERVICE_FOCUS_LABELS.items()
        ],
        "search_modes": [
            {"key": key, "label": label}
            for key, label in SEARCH_MODE_LABELS.items()
        ],
        "service_mixes": [
            {"key": key, "label": label}
            for key, label in SERVICE_MIX_LABELS.items()
        ],
        "market_presets": [
            {
                "key": key,
                "label": val["label"],
                "regions": val.get("regions", []),
                "default_locations": val.get("default_locations", []),
            }
            for key, val in MARKET_PRESETS.items()
        ],
        "service_presets": SERVICE_SEARCH_PRESETS,
        "recommendations": _load_icp_recommendations(),
        "monthly_refresh": _monthly_prospecting_refresh(prospects),
        "note": "Local ICP recommendations and monthly fit review, no API usage.",
    })


@app.route("/api/usage")
def api_usage():
    return jsonify(read_usage_summary())


@app.route("/api/enrichment/audit")
def api_enrichment_audit():
    prospects = [_ensure_fields(p) for p in _load()]
    priority = request.args.get("priority")
    status = request.args.get("status")
    if priority:
        prospects = [p for p in prospects if p.get("priority") == priority]
    if status:
        prospects = [p for p in prospects if p.get("status") == status]
    return jsonify(audit_many(prospects))


@app.route("/api/email/tone-audit")
def api_email_tone_audit():
    prospects = [_ensure_fields(p) for p in _load()]
    summary = audit_many_email_tones(prospects)
    summary.pop("audits_by_id", None)
    if request.args.get("include_leads", "").lower() not in ("1", "true", "yes"):
        summary.pop("leads", None)
    return jsonify(summary)


@app.route("/api/email/review-queue")
def api_email_review_queue():
    prospects = [_ensure_fields(p) for p in _load()]
    include_contacted = request.args.get("include_contacted", "").lower() in ("1", "true", "yes")
    industry = request.args.get("industry", "")
    q = request.args.get("q", "").lower()
    sort_by = request.args.get("sort", "review")
    contacted_statuses = {"sent", "follow-up", "replied", "meeting", "converted"}

    candidates = []
    for p in prospects:
        if not (p.get("email_variants") or p.get("outreach_draft")):
            continue
        if p.get("status") == "skip":
            continue
        if not include_contacted and p.get("status") in contacted_statuses:
            continue
        if industry and p.get("industry") != industry:
            continue
        if q and not (
            q in p.get("name", "").lower()
            or q in p.get("city", "").lower()
            or q in p.get("country", "").lower()
        ):
            continue
        candidates.append(p)

    tone_summary = audit_many_email_tones(candidates)
    rows = []
    flag_counts = {}

    for p in candidates:
        audit = tone_summary["audits_by_id"].get(p.get("id"), audit_email_tone(p))
        flags = _email_review_flags(p, audit)
        if not flags and audit.get("status") == "strong":
            continue

        review_status = _review_status_from_flags(flags, audit.get("status", "strong"))
        for flag in flags:
            code = flag.get("code", "")
            flag_counts[code] = flag_counts.get(code, 0) + int(flag.get("count", 1) or 1)

        rows.append({
            "id": p.get("id", ""),
            "name": p.get("name", ""),
            "industry": p.get("industry", ""),
            "niche": p.get("niche", ""),
            "city": p.get("city", ""),
            "country": p.get("country", ""),
            "score": p.get("score", 0) or 0,
            "priority": p.get("priority", ""),
            "status": p.get("status", ""),
            "brand_gap": p.get("brand_gap", ""),
            "contact_email": p.get("contact_email", ""),
            "tone_audit": audit,
            "review_status": review_status,
            "review_flags": flags,
            "review_reason": ", ".join(f.get("label", f.get("code", "")) for f in flags[:4]),
        })

    if sort_by == "score":
        rows.sort(key=lambda r: (r.get("score") or 0, r.get("name", "").lower()), reverse=True)
    elif sort_by == "name":
        rows.sort(key=lambda r: r.get("name", "").lower())
    elif sort_by == "rating":
        rows.sort(key=lambda r: (r.get("rating") or 0, r.get("score") or 0), reverse=True)
    else:
        def review_sort_key(row):
            codes = {f.get("code") for f in row.get("review_flags", [])}
            status_rank = {"risky": 0, "needs_review": 1, "strong": 2}.get(row.get("review_status"), 2)
            return (
                status_rank,
                0 if "missing_contact_email" in codes else 1,
                0 if "bad_greeting" in codes or "company_fragment_greeting" in codes else 1,
                0 if "old_single_draft" in codes else 1,
                -(row.get("score") or 0),
                row.get("name", "").lower(),
            )
        rows.sort(key=review_sort_key)

    counts = {
        "total": len(rows),
        "risky": sum(1 for r in rows if r.get("review_status") == "risky"),
        "needs_review": sum(1 for r in rows if r.get("review_status") == "needs_review"),
        "missing_email": flag_counts.get("missing_contact_email", 0),
        "bad_greeting": flag_counts.get("bad_greeting", 0) + flag_counts.get("company_fragment_greeting", 0),
        "old_single_draft": flag_counts.get("old_single_draft", 0),
        "weak_evidence": flag_counts.get("weak_evidence", 0),
        "over_80_words": flag_counts.get("over_80_words", 0),
    }

    common_flags = [
        {
            "code": code,
            "label": next(
                (flag.get("label", code) for row in rows for flag in row.get("review_flags", []) if flag.get("code") == code),
                code.replace("_", " ").title(),
            ),
            "count": count,
        }
        for code, count in sorted(flag_counts.items(), key=lambda item: item[1], reverse=True)
    ]

    return jsonify({
        "count": len(rows),
        "counts": counts,
        "common_flags": common_flags,
        "leads": rows,
        "note": "Local review queue, no API usage",
    })


@app.route("/api/email/send-gate", methods=["POST"])
def api_email_send_gate():
    prospects = [_ensure_fields(p) for p in _load()]
    data = request.get_json(force=True) if request.data else {}
    lead_id = (data.get("id") or data.get("lead_id") or "").strip()
    action = (data.get("action") or "send").strip()

    if not lead_id:
        return jsonify({"error": "id is required"}), 400

    variant_index = None
    if data.get("variant_index") not in (None, ""):
        try:
            variant_index = int(data.get("variant_index"))
        except (TypeError, ValueError):
            return jsonify({"error": "variant_index must be a number"}), 400

    lead = _find(prospects, lead_id)
    if not lead:
        return jsonify({"error": "Lead not found"}), 404

    variants = lead.get("email_variants") or []
    if variant_index is not None:
        has_single_draft = bool(lead.get("outreach_draft")) and not variants
        if variants and (variant_index < 0 or variant_index >= len(variants)):
            return jsonify({"error": "variant_index is out of range"}), 400
        if has_single_draft and variant_index != 0:
            return jsonify({"error": "variant_index is out of range"}), 400

    audit, flags = _send_gate_flags(lead, prospects, variant_index=variant_index)
    blocks = [f for f in flags if f.get("code") in SEND_GATE_BLOCKING_CODES]
    warnings = [f for f in flags if f.get("code") not in SEND_GATE_BLOCKING_CODES]

    return jsonify({
        "allowed": not blocks,
        "blocked": bool(blocks),
        "requires_override": bool(warnings) and not blocks,
        "blocks": blocks,
        "warnings": warnings,
        "tone_status": audit.get("status", "strong"),
        "action": action,
        "variant_index": variant_index,
        "note": "Local send gate, no API usage",
    })


@app.route("/api/email/outcome", methods=["POST"])
def api_email_outcome():
    prospects = _load()
    data = request.get_json(force=True) if request.data else {}
    lead_id = (data.get("id") or data.get("lead_id") or "").strip()
    event = (data.get("event") or "save").strip()
    channel = (data.get("channel") or "").strip()

    if not lead_id:
        return jsonify({"error": "id is required"}), 400
    if event not in {"prepared", "sent", "reply", "save"}:
        return jsonify({"error": "Invalid event. Must be prepared, sent, reply, or save"}), 400

    lead = _find(prospects, lead_id)
    if not lead:
        return jsonify({"error": "Lead not found"}), 404
    lead = _ensure_fields(lead)

    variant_index = data.get("variant_index")
    try:
        variant_index = int(variant_index) if variant_index not in (None, "") else None
    except (TypeError, ValueError):
        return jsonify({"error": "variant_index must be a number"}), 400

    if event == "prepared":
        _record_send_prepared(lead, variant_index, channel or "manual")
    elif event == "sent":
        _record_sent(lead, variant_index=variant_index, channel=channel)
        lead["status"] = "sent"
    elif event == "reply":
        _record_reply(
            lead,
            reply_type=(data.get("reply_type") or lead.get("reply_type") or "").strip(),
            reply_notes=data.get("reply_notes", lead.get("reply_notes", "")),
        )
        lead["status"] = "replied"
    else:
        if "variant_sent_index" in data:
            meta = _variant_meta(lead, variant_index)
            lead["variant_sent_index"] = meta["index"]
            lead["variant_sent_label"] = meta["label"]
            lead["variant_sent_approach"] = meta["approach"]
            lead["variant_sent_subject"] = meta["subject"]
        if channel:
            lead["send_channel"] = channel
        if "reply_type" in data:
            lead["reply_type"] = (data.get("reply_type") or "").strip()
        if "reply_notes" in data:
            lead["reply_notes"] = data.get("reply_notes", "")

    _save(prospects)
    return jsonify({
        "lead": lead,
        "event": event,
        "note": "Local outcome tracking, no API usage",
    })


# ---------------------------------------------------------------------------
# Sending safety: kill switch, do-not-contact list, daily cap (Part 4)
# ---------------------------------------------------------------------------

def _read_json_file(path: str, default):
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            return default
    return default


def _write_json_file(path: str, payload) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)
    os.replace(tmp, path)


def _kill_switch_on() -> bool:
    return bool(_read_json_file(SEND_LOCK_JSON, {}).get("paused", False))


def _set_kill_switch(paused: bool) -> None:
    _write_json_file(SEND_LOCK_JSON, {"paused": bool(paused), "updated_at": _now()})


# A send batch can take many minutes (throttled). This guards against a second
# batch starting while one is running (e.g. a retry after a network hiccup),
# which was a cause of duplicate sends. Stale locks older than this are ignored
# so a crashed run cannot wedge sending permanently.
SEND_ACTIVE_STALE_SECONDS = 30 * 60


def _send_in_progress() -> bool:
    rec = _read_json_file(SEND_ACTIVE_JSON, {})
    if not rec.get("active"):
        return False
    started = rec.get("started_at") or ""
    try:
        age = (datetime.now(timezone.utc) - datetime.fromisoformat(started)).total_seconds()
    except (TypeError, ValueError):
        return True
    return age < SEND_ACTIVE_STALE_SECONDS


def _set_send_in_progress(active: bool) -> None:
    _write_json_file(SEND_ACTIVE_JSON, {"active": bool(active), "started_at": _now() if active else ""})


def _load_dnc() -> dict:
    """Do-not-contact list: {emails: [...], domains: [...]} (lowercased)."""
    dnc = _read_json_file(DO_NOT_CONTACT_JSON, {"emails": [], "domains": []})
    dnc.setdefault("emails", [])
    dnc.setdefault("domains", [])
    return dnc


def _is_dnc(email: str, dnc: dict | None = None) -> bool:
    email = (email or "").strip().lower()
    if not email:
        return False
    dnc = dnc or _load_dnc()
    if email in {e.lower() for e in dnc.get("emails", [])}:
        return True
    domain = email.split("@")[-1] if "@" in email else ""
    return bool(domain) and domain in {d.lower().lstrip("@") for d in dnc.get("domains", [])}


def _add_dnc(email: str = "", domain: str = "") -> dict:
    dnc = _load_dnc()
    email = (email or "").strip().lower()
    domain = (domain or "").strip().lower().lstrip("@")
    if email and email not in {e.lower() for e in dnc["emails"]}:
        dnc["emails"].append(email)
    if domain and domain not in {d.lower() for d in dnc["domains"]}:
        dnc["domains"].append(domain)
    _write_json_file(DO_NOT_CONTACT_JSON, dnc)
    return dnc


def _send_count_today() -> int:
    rec = _read_json_file(SEND_COUNTER_JSON, {})
    return int(rec.get("count", 0)) if rec.get("date") == _today() else 0


def _bump_send_count() -> int:
    count = _send_count_today() + 1
    _write_json_file(SEND_COUNTER_JSON, {"date": _today(), "count": count})
    return count


def _already_contacted_emails(prospects: list[dict], exclude_id: str = "") -> set:
    contacted_statuses = {"sent", "follow-up", "replied", "meeting", "converted"}
    return {
        (p.get("contact_email") or "").strip().lower()
        for p in prospects
        if p.get("status") in contacted_statuses
        and p.get("id") != exclude_id
        and (p.get("contact_email") or "").strip()
    }


def _pre_send_gate(lead: dict, prospects: list[dict], contacted: set | None = None,
                   dnc: dict | None = None) -> str | None:
    """Hard pre-send checks. Returns a block reason string, or None if clear.

    Enforces: kill switch, valid recipient, do-not-contact, never-send-twice,
    and blocking tone-audit codes. These skip the lead, they are not advisory.
    """
    if _kill_switch_on():
        return "Sending paused (kill switch on)"

    email = (lead.get("contact_email") or "").strip().lower()
    if not email:
        return "No contact email"
    if _is_dnc(email, dnc):
        return "On do-not-contact list"

    contacted = _already_contacted_emails(prospects, exclude_id=lead.get("id", "")) if contacted is None else contacted
    if email in contacted:
        return "Already contacted this address"

    _audit, flags = _send_gate_flags(lead, prospects, variant_index=_approved_index(lead))
    blocks = [f for f in flags if f.get("code") in SEND_GATE_BLOCKING_CODES]
    if blocks:
        return "Blocked by tone gate: " + ", ".join(b.get("label", b.get("code", "")) for b in blocks)
    return None


# ---------------------------------------------------------------------------
# Sending: variant payload, archive, log (Part 2)
# ---------------------------------------------------------------------------

def _approved_index(lead: dict):
    idx = lead.get("approved_variant")
    try:
        return int(idx) if idx not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _variant_send_payload(lead: dict, variant_index: int | None) -> dict:
    """Return {subject, body} for the chosen variant, with signature appended."""
    variants = lead.get("email_variants") or []
    if variants:
        if variant_index is None or variant_index < 0 or variant_index >= len(variants):
            variant_index = 0
        v = variants[variant_index]
        subject = (v.get("subject") or lead.get("outreach_subject") or "").strip()
        body = (v.get("body") or "").strip()
    else:
        subject = (lead.get("outreach_subject") or "").strip()
        body = (lead.get("outreach_draft") or "").strip()
    # Optional AI add-on: a short P.S. that rides along with the branding email.
    if body and _truthy(lead.get("ai_addon_enabled")) and (lead.get("ai_addon") or "").strip():
        body = body + "\n\n" + lead["ai_addon"].strip()
    full_body = body + "\n\n" + EMAIL_SIGNATURE if body else EMAIL_SIGNATURE
    return {"subject": subject, "body": full_body, "index": variant_index or 0}


def _slugify(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")
    return slug[:60] or "lead"


def _archive_sent_email(lead: dict, payload: dict) -> None:
    """Write emails/YYYY-MM-DD_company.md (fulfils CLAUDE.md Section 3)."""
    os.makedirs(EMAILS_DIR, exist_ok=True)
    fname = f"{_today()}_{_slugify(lead.get('name', ''))}.md"
    path = os.path.join(EMAILS_DIR, fname)
    content = (
        f"# {lead.get('name', 'Unknown')}\n\n"
        f"- To: {lead.get('contact_email', '')}\n"
        f"- Sent: {_today()}\n"
        f"- Variant: {lead.get('variant_sent_label', '')} ({lead.get('variant_sent_approach', '')})\n"
        f"- Score: {lead.get('score', 0)} / {lead.get('priority', '')}\n"
        f"- Gmail thread: {lead.get('gmail_thread_id', '')}\n\n"
        f"## Subject\n{payload.get('subject', '')}\n\n"
        f"## Body\n{payload.get('body', '')}\n"
    )
    try:
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
    except OSError as e:
        print(f"[archive] could not write {path}: {e}")


def _append_email_log(lead: dict) -> None:
    """Append one row to email-log.md (creates header if missing)."""
    row = "| {company} | {contact} | {score} | {sent} | {status} | {variant} | {notes} |\n".format(
        company=lead.get("name", "").replace("|", "/"),
        contact=lead.get("contact_email", ""),
        score=lead.get("score", 0),
        sent=lead.get("date_sent", _today()),
        status=lead.get("status", "sent"),
        variant=lead.get("variant_sent_label", ""),
        notes="",
    )
    try:
        if not os.path.exists(EMAIL_LOG_MD):
            with open(EMAIL_LOG_MD, "w", encoding="utf-8") as f:
                f.write("# Email Outreach Log\n\n")
                f.write("| Company | Contact | Score | Sent | Status | Variant | Notes |\n")
                f.write("|---------|---------|-------|------|--------|---------|-------|\n")
        with open(EMAIL_LOG_MD, "a", encoding="utf-8") as f:
            f.write(row)
    except OSError as e:
        print(f"[email-log] could not append: {e}")


def _update_email_log_status(lead: dict, status: str, note: str = "") -> None:
    """Update Status (and Notes) on the lead's most recent row in
    email-log.md, so automatic reply/bounce detection keeps the log in sync.
    Appends a fresh row if the company has none yet."""
    company = (lead.get("name", "") or "").replace("|", "/").strip()
    if not company:
        return
    if not os.path.exists(EMAIL_LOG_MD):
        _append_email_log(lead)
        return
    try:
        with open(EMAIL_LOG_MD, "r", encoding="utf-8") as f:
            lines = f.readlines()
        target = None
        for i in range(len(lines) - 1, -1, -1):
            cells = lines[i].split("|")
            if len(cells) >= 8 and cells[1].strip() == company:
                target = i
                break
        if target is None:
            _append_email_log(lead)
            return
        cells = lines[target].split("|")
        cells[5] = f" {status} "
        if note:
            cells[-2] = f" {note.replace('|', '/')} "
        lines[target] = "|".join(cells)
        if not lines[target].endswith("\n"):
            lines[target] += "\n"
        with open(EMAIL_LOG_MD, "w", encoding="utf-8") as f:
            f.writelines(lines)
    except OSError as e:
        print(f"[email-log] could not update: {e}")


# ---------------------------------------------------------------------------
# Approve + batch send (Part 2b)
# ---------------------------------------------------------------------------

@app.route("/api/email/approve", methods=["POST"])
def api_email_approve():
    """Mark a lead's chosen variant approved and queued. Sends nothing."""
    prospects = _load()
    data = request.get_json(force=True) if request.data else {}
    lead_id = (data.get("id") or data.get("lead_id") or "").strip()
    if not lead_id:
        return jsonify({"error": "id is required"}), 400

    lead = _find(prospects, lead_id)
    if not lead:
        return jsonify({"error": "Lead not found"}), 404
    lead = _ensure_fields(lead)

    unapprove = bool(data.get("unapprove"))
    if unapprove:
        lead["approved_variant"] = None
        lead["approved_at"] = None
        _save(prospects)
        return jsonify({"lead": lead, "approved": False})

    variant_index = data.get("variant_index")
    try:
        variant_index = int(variant_index) if variant_index not in (None, "") else 0
    except (TypeError, ValueError):
        return jsonify({"error": "variant_index must be a number"}), 400

    variants = lead.get("email_variants") or []
    if variants and (variant_index < 0 or variant_index >= len(variants)):
        return jsonify({"error": "variant_index is out of range"}), 400
    if not variants and not (lead.get("outreach_draft") or "").strip():
        return jsonify({"error": "Lead has no email draft to approve"}), 400

    lead["approved_variant"] = variant_index
    lead["approved_at"] = _now()
    _record_send_prepared(lead, variant_index, "gmail")
    _save(prospects)
    return jsonify({"lead": lead, "approved": True})


@app.route("/api/email/approved-count")
def api_email_approved_count():
    prospects = [_ensure_fields(p) for p in _load()]
    pending = [p for p in prospects
               if _approved_index(p) is not None and p.get("status") != "sent"]
    leads = []
    for p in pending:
        idx = _approved_index(p)
        meta = _variant_meta(p, idx)
        leads.append({
            "id": p.get("id"),
            "name": p.get("name"),
            "contact_email": p.get("contact_email") or p.get("contact_page_email") or "",
            "variant_index": idx,
            "variant_label": meta.get("label") or "",
            "subject": meta.get("subject") or "",
            "approved_at": p.get("approved_at") or "",
        })
    return jsonify({
        "count": len(pending),
        "leads": leads,
        "kill_switch": _kill_switch_on(),
        "sent_today": _send_count_today(),
        "daily_cap": DAILY_SEND_CAP,
        "gmail": validate_keys().get("gmail"),
    })


@app.route("/api/email/send-approved", methods=["POST"])
def api_email_send_approved():
    """Send every approved-but-not-sent lead via Gmail, with throttle + cap.

    Stops immediately if the kill switch flips. Each lead passes _pre_send_gate
    or is skipped with a logged reason. Sends are spaced by SEND_DELAY_SECONDS.
    """
    from mailer import gmail_client

    data = request.get_json(force=True) if request.data else {}
    limit = data.get("limit")
    try:
        limit = int(limit) if limit not in (None, "") else None
    except (TypeError, ValueError):
        limit = None

    if not gmail_client.is_configured():
        return jsonify({"error": "Gmail not authorized. Run: python authorize_gmail.py"}), 400
    if _kill_switch_on():
        return jsonify({"error": "Sending is paused (kill switch on). Turn it off to send."}), 409
    if _send_in_progress():
        return jsonify({"error": "A send batch is already running. Wait for it to finish."}), 409

    _set_send_in_progress(True)
    try:
        return _run_send_approved(gmail_client, limit)
    finally:
        _set_send_in_progress(False)


def _run_send_approved(gmail_client, limit):
    prospects = _load()
    prospects = [_ensure_fields(p) for p in prospects]
    dnc = _load_dnc()
    contacted = _already_contacted_emails(prospects)

    queue = [p for p in prospects
             if _approved_index(p) is not None and p.get("status") != "sent"]
    if limit:
        queue = queue[:limit]

    sent, skipped, results = 0, 0, []
    cap_reached = False

    for i, lead in enumerate(queue):
        if _kill_switch_on():
            results.append({"id": lead["id"], "name": lead.get("name"), "result": "stopped", "reason": "kill switch"})
            break
        if _send_count_today() >= DAILY_SEND_CAP:
            cap_reached = True
            results.append({"id": lead["id"], "name": lead.get("name"), "result": "held", "reason": "daily cap reached"})
            break

        # Idempotency: a lead that already carries a Gmail message id was sent
        # before (even if a crash left status != "sent"). Never send it again.
        if (lead.get("gmail_message_id") or "").strip():
            if lead.get("status") != "sent":
                lead["status"] = "sent"
                _save(prospects)
            skipped += 1
            results.append({"id": lead["id"], "name": lead.get("name"), "result": "skipped", "reason": "Already sent (has Gmail message id)"})
            continue

        reason = _pre_send_gate(lead, prospects, contacted=contacted, dnc=dnc)
        if reason:
            lead["send_blocked_reason"] = reason
            skipped += 1
            results.append({"id": lead["id"], "name": lead.get("name"), "result": "skipped", "reason": reason})
            continue

        idx = _approved_index(lead)
        payload = _variant_send_payload(lead, idx)
        if not payload["subject"] or not payload["body"].strip():
            skipped += 1
            results.append({"id": lead["id"], "name": lead.get("name"), "result": "skipped", "reason": "empty subject/body"})
            continue

        # Throttle between actual sends (not before the first).
        if sent > 0 and SEND_DELAY_SECONDS > 0:
            time.sleep(SEND_DELAY_SECONDS)

        try:
            res = gmail_client.send_email(
                to=lead["contact_email"],
                subject=payload["subject"],
                body_text=payload["body"],
            )
        except Exception as e:
            lead["send_blocked_reason"] = f"Gmail error: {e}"
            skipped += 1
            results.append({"id": lead["id"], "name": lead.get("name"), "result": "error", "reason": str(e)})
            continue

        lead["gmail_message_id"] = res.get("message_id", "")
        lead["gmail_thread_id"] = res.get("thread_id", "")
        lead["send_blocked_reason"] = ""
        lead["approved_variant"] = None
        lead["approved_at"] = None
        _record_sent(lead, variant_index=idx, channel="gmail")
        lead["status"] = "sent"
        _archive_sent_email(lead, payload)
        _append_email_log(lead)
        contacted.add((lead.get("contact_email") or "").strip().lower())
        _bump_send_count()
        sent += 1
        results.append({"id": lead["id"], "name": lead.get("name"), "result": "sent"})
        # Persist immediately so a crash or network drop after this point can
        # never resend this lead (the on-disk record is now status="sent").
        _save(prospects)

    _save(prospects)
    return jsonify({
        "sent": sent,
        "skipped": skipped,
        "cap_reached": cap_reached,
        "sent_today": _send_count_today(),
        "daily_cap": DAILY_SEND_CAP,
        "results": results,
    })


@app.route("/api/email/kill-switch", methods=["GET", "POST"])
def api_email_kill_switch():
    if request.method == "POST":
        data = request.get_json(force=True) if request.data else {}
        _set_kill_switch(bool(data.get("paused")))
    return jsonify({"paused": _kill_switch_on()})


@app.route("/api/email/do-not-contact", methods=["GET", "POST"])
def api_email_do_not_contact():
    if request.method == "POST":
        data = request.get_json(force=True) if request.data else {}
        _add_dnc(email=data.get("email", ""), domain=data.get("domain", ""))
    return jsonify(_load_dnc())


def _is_bounce_message(from_header: str) -> bool:
    sender = (from_header or "").lower()
    return "mailer-daemon" in sender or "postmaster" in sender


def _check_replies_core(gmail_client) -> dict:
    """Read-only Gmail check on sent threads. Classifies inbound messages:
    mailer-daemon/postmaster -> lead becomes 'bounced', anything else ->
    'replied'. A human reply always wins over a bounce in the same thread
    (a resend after a bounce can still get answered)."""
    prospects = [_ensure_fields(p) for p in _load()]
    open_statuses = {"sent", "follow-up", "bounced"}
    by_thread = {p.get("gmail_thread_id"): p for p in prospects
                 if p.get("gmail_thread_id") and p.get("status") in open_statuses}
    if not by_thread:
        return {"checked": 0, "new_replies": 0, "new_bounces": 0, "replies": [], "bounces": []}

    replies = gmail_client.list_replies(list(by_thread.keys()))

    # Group inbound messages per thread so a human reply beats a bounce.
    inbound_by_thread: dict[str, list[dict]] = defaultdict(list)
    for r in replies:
        inbound_by_thread[r["thread_id"]].append(r)

    new_replies, new_bounces = [], []
    for tid, msgs in inbound_by_thread.items():
        lead = by_thread.get(tid)
        if not lead:
            continue
        human = [m for m in msgs if not _is_bounce_message(m.get("from", ""))]
        if human:
            if lead.get("status") == "replied":
                continue
            r = human[-1]
            lead["status"] = "replied"
            lead["reply_snippet"] = r.get("snippet", "")
            lead["reply_from"] = r.get("from", "")
            lead["reply_received_at"] = r.get("received_at", "") or _now()
            lead["date_replied"] = _today()
            lead["reply_recorded_at"] = _now()
            _update_email_log_status(
                lead, "replied",
                note=f"replied {_today()}: {(r.get('snippet', '') or '')[:80]}")
            new_replies.append({"id": lead["id"], "name": lead.get("name"),
                                "from": r.get("from", ""), "snippet": r.get("snippet", "")})
        else:
            if lead.get("status") == "bounced":
                continue
            b = msgs[-1]
            lead["status"] = "bounced"
            lead["bounce_snippet"] = b.get("snippet", "")
            lead["bounce_from"] = b.get("from", "")
            lead["bounce_received_at"] = b.get("received_at", "") or _now()
            lead["date_bounced"] = _today()
            lead["bounce_recorded_at"] = _now()
            _update_email_log_status(lead, "bounced", note=f"bounced {_today()}")
            new_bounces.append({"id": lead["id"], "name": lead.get("name"),
                                "snippet": b.get("snippet", "")})

    if new_replies or new_bounces:
        _save(prospects)
    return {"checked": len(by_thread), "new_replies": len(new_replies),
            "new_bounces": len(new_bounces), "replies": new_replies, "bounces": new_bounces}


@app.route("/api/email/check-replies", methods=["POST"])
def api_email_check_replies():
    """Gmail check for replies and bounces on sent threads."""
    from mailer import gmail_client

    if not gmail_client.is_configured():
        return jsonify({"error": "Gmail not authorized. Run: python authorize_gmail.py"}), 400
    try:
        return jsonify(_check_replies_core(gmail_client))
    except Exception as e:
        return jsonify({"error": f"Gmail error: {e}"}), 502


@app.route("/api/email/requeue-bounced", methods=["POST"])
def api_email_requeue_bounced():
    """Return bounced leads to 'drafted' so they can be re-approved and resent.

    Archives the failed send's Gmail ids (they otherwise trip the never-send-
    twice idempotency guard) and clears the sent record. Leads are NOT
    auto-approved: review the contact email first, a bounce can mean a bad
    address, then approve again."""
    prospects = [_ensure_fields(p) for p in _load()]
    requeued = []
    for lead in prospects:
        if lead.get("status") != "bounced":
            continue
        lead["bounce_count"] = int(lead.get("bounce_count") or 0) + 1
        lead["bounced_gmail_message_id"] = lead.get("gmail_message_id", "")
        lead["bounced_gmail_thread_id"] = lead.get("gmail_thread_id", "")
        lead["gmail_message_id"] = ""
        lead["gmail_thread_id"] = ""
        _clear_sent_record(lead)
        lead["status"] = "drafted"
        lead["bounce_requeued_at"] = _now()
        _update_email_log_status(
            lead, "drafted",
            note=f"bounced {lead.get('date_bounced', '')}, requeued {_today()}")
        requeued.append({"id": lead["id"], "name": lead.get("name"),
                         "contact_email": lead.get("contact_email", "")})
    if requeued:
        _save(prospects)
    return jsonify({"requeued": len(requeued), "leads": requeued})


@app.route("/api/email/follow-up-queue")
def api_email_follow_up_queue():
    """Sent leads with no reply after FOLLOW_UP_DAYS, never replied/meeting/converted."""
    prospects = [_ensure_fields(p) for p in _load()]
    today = date.today()
    due = []
    for p in prospects:
        if p.get("status") != "sent" or not p.get("date_sent"):
            continue
        try:
            sent_day = date.fromisoformat(str(p["date_sent"])[:10])
        except ValueError:
            continue
        if (today - sent_day).days >= FOLLOW_UP_DAYS:
            due.append({
                "id": p["id"],
                "name": p.get("name"),
                "contact_email": p.get("contact_email"),
                "date_sent": p.get("date_sent"),
                "days_since": (today - sent_day).days,
                "variant_sent_label": p.get("variant_sent_label", ""),
                "follow_up_count": p.get("follow_up_count", 0),
            })
    due.sort(key=lambda x: x["days_since"], reverse=True)
    return jsonify({"count": len(due), "leads": due, "threshold_days": FOLLOW_UP_DAYS})


# ---------------------------------------------------------------------------
# Follow-up engine: export due leads -> Claude writes bumps -> import -> send
# as threaded Gmail replies. Mirrors the score/write file-handoff pattern.
# ---------------------------------------------------------------------------

FOLLOWUP_EXPORT_JSON = os.path.join(DATA_DIR, "to_followup.json")
FOLLOWUP_WRITTEN_JSON = os.path.join(DATA_DIR, "followup_written.json")

FOLLOWUP_MAX_WORDS = 60
_FOLLOWUP_BUMP_PHRASES = [
    "just following up", "following up on my", "bumping this", "bump this",
    "floating this", "circling back", "checking in", "top of your inbox",
]


def _followup_word_count(text: str) -> int:
    return len(re.findall(r"\b[\w']+\b", text or ""))


def _followup_block_reasons(body: str) -> list[str]:
    """Hard checks a follow-up must pass before sending."""
    reasons = []
    text = body or ""
    if "—" in text or "–" in text:
        reasons.append("contains an em or en dash")
    if re.search(r"\b(15[- ]?minute|book a call|schedule|meeting|quick call|call make sense)\b", text, re.IGNORECASE):
        reasons.append("asks for a meeting")
    lower = text.lower()
    for phrase in _FOLLOWUP_BUMP_PHRASES:
        if phrase in lower:
            reasons.append(f"lazy bump phrase: `{phrase}`")
            break
    words = _followup_word_count(text)
    if words > FOLLOWUP_MAX_WORDS:
        reasons.append(f"{words} words; follow-ups stay under {FOLLOWUP_MAX_WORDS}")
    if not text.strip():
        reasons.append("empty body")
    return reasons


def _sent_variant_of(lead: dict) -> dict:
    variants = lead.get("email_variants") or []
    idx = lead.get("variant_sent_index")
    try:
        idx = int(idx) if idx not in (None, "") else 0
    except (TypeError, ValueError):
        idx = 0
    if variants and 0 <= idx < len(variants):
        return variants[idx]
    return {"subject": lead.get("outreach_subject", ""), "body": lead.get("outreach_draft", "")}


def _followup_due_for_export(prospects: list[dict]) -> list[dict]:
    """Sent leads past FOLLOW_UP_DAYS with a Gmail thread to reply into and no
    follow-up drafted or sent yet."""
    today = date.today()
    due = []
    for p in prospects:
        if p.get("status") != "sent" or not p.get("date_sent"):
            continue
        if not p.get("gmail_thread_id"):
            continue  # a threaded reply needs the original thread
        if (p.get("follow_up_body") or "").strip() or (p.get("gmail_followup_message_id") or "").strip():
            continue
        try:
            sent_day = date.fromisoformat(str(p["date_sent"])[:10])
        except ValueError:
            continue
        if (today - sent_day).days >= FOLLOW_UP_DAYS:
            due.append(p)
    return due


@app.route("/api/email/export-followups", methods=["POST"])
def api_email_export_followups():
    """Write data/to_followup.json for Claude to draft threaded bumps."""
    prospects = [_ensure_fields(p) for p in _load()]
    due = _followup_due_for_export(prospects)
    today = date.today()
    out = []
    for p in due:
        sent_v = _sent_variant_of(p)
        out.append({
            "id": p["id"],
            "name": p.get("name", ""),
            "city": p.get("city", ""),
            "industry": p.get("source_industry") or p.get("industry") or "",
            "search_mode": p.get("search_mode", ""),
            "partner_lane": p.get("partner_lane", False),
            "contact_email": p.get("contact_email", ""),
            "decision_maker": p.get("decision_maker", ""),
            "date_sent": p.get("date_sent", ""),
            "days_since": (today - date.fromisoformat(str(p["date_sent"])[:10])).days,
            "follow_up_count": p.get("follow_up_count", 0),
            "sent_subject": p.get("variant_sent_subject") or sent_v.get("subject", ""),
            "sent_body": sent_v.get("body", ""),
            "trigger": p.get("trigger", ""),
            "website_summary": p.get("website_summary", ""),
            "brand_signals": p.get("brand_signals", ""),
        })
    with open(FOLLOWUP_EXPORT_JSON, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)
    return jsonify({"exported": len(out), "file": "data/to_followup.json",
                    "next": 'Ask Claude Code: "write follow-ups"'})


@app.route("/api/email/import-followups", methods=["POST"])
def api_email_import_followups():
    """Import data/followup_written.json ([{id, body}]) into follow_up_body."""
    if not os.path.exists(FOLLOWUP_WRITTEN_JSON):
        return jsonify({"error": "data/followup_written.json not found. Ask Claude to write follow-ups first."}), 400
    try:
        with open(FOLLOWUP_WRITTEN_JSON, "r", encoding="utf-8") as f:
            entries = json.load(f)
    except json.JSONDecodeError as e:
        return jsonify({"error": f"followup_written.json is not valid JSON: {e}"}), 400
    if not isinstance(entries, list):
        return jsonify({"error": "followup_written.json must be an array"}), 400

    prospects = [_ensure_fields(p) for p in _load()]
    imported, warnings, missing = 0, [], []
    for entry in entries:
        lead = _find(prospects, str(entry.get("id", "")))
        if not lead:
            missing.append(entry.get("id", ""))
            continue
        body = (entry.get("body") or "").strip()
        issues = _followup_block_reasons(body)
        lead["follow_up_body"] = body
        lead["follow_up_written_at"] = _now()
        imported += 1
        if issues:
            warnings.append({"id": lead["id"], "name": lead.get("name"), "issues": issues})
    _save(prospects)
    # Archive the import file so a stale one is never re-imported by mistake.
    stamp = _now().replace(":", "-").replace(".", "-")
    try:
        os.replace(FOLLOWUP_WRITTEN_JSON, FOLLOWUP_WRITTEN_JSON.replace(".json", f"-{stamp}.json"))
    except OSError:
        pass
    return jsonify({"imported": imported, "missing_ids": missing, "warnings": warnings})


@app.route("/api/email/send-followups", methods=["POST"])
def api_email_send_followups():
    """Send drafted follow-ups as threaded Gmail replies, throttled + capped."""
    from mailer import gmail_client

    if not gmail_client.is_configured():
        return jsonify({"error": "Gmail not authorized. Run: python authorize_gmail.py"}), 400
    if _kill_switch_on():
        return jsonify({"error": "Sending is paused (kill switch on). Turn it off to send."}), 409
    if _send_in_progress():
        return jsonify({"error": "A send batch is already running. Wait for it to finish."}), 409

    _set_send_in_progress(True)
    try:
        return _run_send_followups(gmail_client)
    finally:
        _set_send_in_progress(False)


def _run_send_followups(gmail_client):
    prospects = [_ensure_fields(p) for p in _load()]
    queue = [p for p in prospects
             if p.get("status") == "sent"
             and (p.get("follow_up_body") or "").strip()
             and p.get("gmail_thread_id")]

    sent, skipped, results = 0, 0, []
    cap_reached = False
    for lead in queue:
        if _kill_switch_on():
            results.append({"id": lead["id"], "name": lead.get("name"), "result": "stopped", "reason": "kill switch"})
            break
        if _send_count_today() >= DAILY_SEND_CAP:
            cap_reached = True
            results.append({"id": lead["id"], "name": lead.get("name"), "result": "held", "reason": "daily cap reached"})
            break
        # Idempotency: one follow-up per lead until the field is cleared.
        if (lead.get("gmail_followup_message_id") or "").strip():
            skipped += 1
            results.append({"id": lead["id"], "name": lead.get("name"), "result": "skipped", "reason": "Follow-up already sent"})
            continue
        if not (lead.get("contact_email") or "").strip():
            skipped += 1
            results.append({"id": lead["id"], "name": lead.get("name"), "result": "skipped", "reason": "No contact email"})
            continue
        body = lead["follow_up_body"].strip()
        issues = _followup_block_reasons(body)
        if issues:
            skipped += 1
            results.append({"id": lead["id"], "name": lead.get("name"), "result": "skipped", "reason": "; ".join(issues)})
            continue

        base_subject = (lead.get("variant_sent_subject") or lead.get("outreach_subject") or "").strip()
        subject = base_subject if base_subject.lower().startswith("re:") else f"Re: {base_subject}"
        full_body = body + "\n\n" + EMAIL_SIGNATURE

        if sent > 0 and SEND_DELAY_SECONDS > 0:
            time.sleep(SEND_DELAY_SECONDS)
        try:
            res = gmail_client.send_email(
                to=lead["contact_email"],
                subject=subject,
                body_text=full_body,
                thread_id=lead["gmail_thread_id"],
            )
        except Exception as e:
            skipped += 1
            results.append({"id": lead["id"], "name": lead.get("name"), "result": "error", "reason": str(e)})
            continue

        lead["gmail_followup_message_id"] = res.get("message_id", "")
        lead["follow_up_count"] = int(lead.get("follow_up_count") or 0) + 1
        lead["date_followed_up"] = _today()
        lead["follow_up_sent_body"] = body
        lead["follow_up_body"] = ""
        lead["status"] = "follow-up"
        _bump_send_count()
        sent += 1
        results.append({"id": lead["id"], "name": lead.get("name"), "result": "sent"})
        _update_email_log_status(lead, "follow-up", note=f"follow-up sent {_today()}")
        # Persist immediately so a crash can never resend this follow-up.
        _save(prospects)

    _save(prospects)
    return jsonify({
        "sent": sent,
        "skipped": skipped,
        "cap_reached": cap_reached,
        "sent_today": _send_count_today(),
        "daily_cap": DAILY_SEND_CAP,
        "results": results,
    })


@app.route("/api/memory/add-win", methods=["POST"])
def api_memory_add_win():
    """Append a one-line win under '## What Works' in the shared memory.md."""
    data = request.get_json(force=True) if request.data else {}
    lead_id = (data.get("id") or "").strip()

    note = (data.get("note") or "").strip()
    if not note and lead_id:
        lead = _find([_ensure_fields(p) for p in _load()], lead_id)
        if lead:
            approach = lead.get("variant_sent_approach") or ""
            subj = lead.get("variant_sent_subject") or lead.get("outreach_subject") or ""
            ind = lead.get("source_industry") or lead.get("industry") or ""
            note = f'{approach.title()} variant won a reply ({ind}): "{subj}"'.strip()
    if not note:
        return jsonify({"error": "Nothing to add. Provide a note or a replied lead id."}), 400

    if not os.path.exists(MEMORY_MD):
        return jsonify({"error": f"memory.md not found at {MEMORY_MD}"}), 404

    with open(MEMORY_MD, "r", encoding="utf-8") as f:
        lines = f.readlines()

    bullet = f"- {note}\n"
    header_idx = next((i for i, ln in enumerate(lines) if ln.strip() == "## What Works"), None)
    if header_idx is None:
        lines.append("\n## What Works\n")
        lines.append(bullet)
    else:
        insert_at = header_idx + 1
        while insert_at < len(lines) and not lines[insert_at].startswith("## "):
            insert_at += 1
        lines.insert(insert_at, bullet)

    tmp = MEMORY_MD + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.writelines(lines)
    os.replace(tmp, MEMORY_MD)
    return jsonify({"added": note})


@app.route("/api/enrichment/snapshots/<lead_id>")
def api_enrichment_snapshots(lead_id):
    prospects = _load()
    lead = _find(prospects, lead_id)
    if not lead:
        return jsonify({"error": "Lead not found"}), 404
    lead = _ensure_fields(lead)
    return jsonify({
        "lead_id": lead_id,
        "snapshots": _snapshot_records_for_lead(lead),
        "note": "Local snapshot, no API usage",
    })


@app.route("/api/enrichment/snapshots/<lead_id>/<snapshot_id>")
def api_enrichment_snapshot_detail(lead_id, snapshot_id):
    prospects = _load()
    lead = _find(prospects, lead_id)
    if not lead:
        return jsonify({"error": "Lead not found"}), 404
    lead = _ensure_fields(lead)
    path = _snapshot_path_for_lead(lead, snapshot_id)
    if not path:
        return jsonify({"error": "Snapshot not found for this lead"}), 404
    try:
        with open(path, "r", encoding="utf-8-sig") as f:
            snapshot = json.load(f)
    except json.JSONDecodeError as e:
        return jsonify({
            "error": f"Invalid snapshot JSON: {e.msg} at line {e.lineno}, column {e.colno}"
        }), 400
    return jsonify({
        "lead_id": lead_id,
        "snapshot_id": snapshot_id,
        "snapshot": snapshot,
        "note": "Local snapshot, no API usage",
    })


# ---------------------------------------------------------------------------
# API: Industries
# ---------------------------------------------------------------------------

@app.route("/api/industries")
def api_industries():
    industries = [
        {"key": k, "label": INDUSTRY_LABELS.get(k, k), "query": v}
        for k, v in INDUSTRY_QUERIES.items()
    ]
    return jsonify({
        "industries": industries,
        "services": [{"key": k, "label": v} for k, v in SERVICE_FOCUS_LABELS.items()],
        "search_modes": [{"key": k, "label": v} for k, v in SEARCH_MODE_LABELS.items()],
        "service_mixes": [{"key": k, "label": v} for k, v in SERVICE_MIX_LABELS.items()],
        "market_presets": [
            {
                "key": key,
                "label": val["label"],
                "regions": val.get("regions", []),
                "default_locations": val.get("default_locations", []),
            }
            for key, val in MARKET_PRESETS.items()
        ],
        "service_presets": SERVICE_SEARCH_PRESETS,
    })


# ---------------------------------------------------------------------------
# API: Leads
# ---------------------------------------------------------------------------

@app.route("/api/leads")
def api_leads():
    prospects = _load()
    leads = [_ensure_fields(p) for p in prospects]

    # Filters
    status   = request.args.get("status")
    industry = request.args.get("industry")
    priority = request.args.get("priority")
    favorite = request.args.get("favorite")
    missing_email = request.args.get("missing_email")
    q        = request.args.get("q", "").lower()
    sort_by  = request.args.get("sort", "found_at")
    order    = request.args.get("order", "desc")

    if missing_email and _truthy(missing_email):
        # Drafted leads with no contact_email = blocked from Gmail send.
        leads = [p for p in leads
                 if p.get("status") == "drafted" and not (p.get("contact_email") or "").strip()]
    if status:
        if status == "scored":
            # "scored" filter shows all leads that have been scored (any priority)
            leads = [p for p in leads if p.get("priority") in ("hot", "warm", "cold")]
        else:
            leads = [p for p in leads if p.get("status") == status]
    if industry:
        leads = [p for p in leads if p.get("industry") == industry]
    if priority:
        leads = [p for p in leads if p.get("priority") == priority]
    if favorite and _truthy(favorite):
        leads = [p for p in leads if p.get("is_favorite")]
    if q:
        leads = [p for p in leads if
                 q in p.get("name", "").lower() or
                 q in p.get("city", "").lower() or
                 q in p.get("country", "").lower()]

    _sort_leads(leads, sort_by, order)

    return jsonify({"leads": leads, "count": len(leads)})


@app.route("/api/favorites")
def api_favorites():
    prospects = _load()
    leads = [_ensure_fields(p) for p in prospects if _truthy(p.get("is_favorite", p.get("favorite", False)))]

    industry = request.args.get("industry")
    q        = request.args.get("q", "").lower()
    sort_by  = request.args.get("sort", "favorited_at")
    order    = request.args.get("order", "desc")

    if industry:
        leads = [p for p in leads if p.get("industry") == industry]
    if q:
        leads = [p for p in leads if
                 q in p.get("name", "").lower() or
                 q in p.get("city", "").lower() or
                 q in p.get("country", "").lower() or
                 q in p.get("favorite_note", "").lower()]

    _sort_leads(leads, sort_by, order)

    return jsonify({"leads": leads, "favorites": leads, "count": len(leads)})


@app.route("/api/leads/<lead_id>")
def api_lead_detail(lead_id):
    prospects = _load()
    lead = _find(prospects, lead_id)
    if not lead:
        return jsonify({"error": "Lead not found"}), 404
    return jsonify({"lead": _ensure_fields(lead)})


@app.route("/api/leads/<lead_id>/favorite", methods=["POST"])
def api_lead_favorite(lead_id):
    prospects = _load()
    lead = _find(prospects, lead_id)
    if not lead:
        return jsonify({"error": "Lead not found"}), 404

    _ensure_fields(lead)
    data = request.get_json(force=True) if request.data else {}
    note_supplied = "favorite_note" in data

    if "is_favorite" in data:
        want_favorite = _truthy(data.get("is_favorite"))
    elif "favorite" in data:
        want_favorite = _truthy(data.get("favorite"))
    else:
        want_favorite = True if note_supplied else not _truthy(lead.get("is_favorite"))

    if note_supplied:
        note = str(data.get("favorite_note") or "").strip()
        if len(note) > 1200:
            return jsonify({"error": "Favorite note is too long. Keep it under 1200 characters."}), 400
        lead["favorite_note"] = note

    if want_favorite:
        if not _truthy(lead.get("is_favorite")):
            lead["favorited_at"] = _now()
            lead["favorite_order"] = _next_favorite_order(prospects)
        elif not lead.get("favorited_at"):
            lead["favorited_at"] = _now()
        if not lead.get("favorite_order"):
            lead["favorite_order"] = _next_favorite_order(prospects)
        lead["is_favorite"] = True
    else:
        lead["is_favorite"] = False
        lead["favorited_at"] = None
        lead["favorite_order"] = None

    _save(prospects)
    favorite_count = sum(1 for p in prospects if _truthy(p.get("is_favorite")))
    return jsonify({"lead": _ensure_fields(lead), "favorite_count": favorite_count})


@app.route("/api/leads", methods=["POST"])
def api_add_lead():
    data = request.get_json(force=True)
    name = data.get("name", "").strip()
    if not name:
        return jsonify({"error": "Name is required"}), 400

    industry = data.get("industry", "other")

    lead = {
        "id":              f"manual-{_now().replace(':', '-')}",
        "name":            name,
        "industry":        industry,
        "niche":           INDUSTRY_LABELS.get(industry, industry.title()),
        "region":          data.get("region", ""),
        "address":         data.get("address", ""),
        "city":            data.get("city", ""),
        "country":         data.get("country", ""),
        "phone":           data.get("phone", ""),
        "website":         data.get("website", ""),
        "google_maps_url": data.get("google_maps_url", ""),
        "rating":          float(data.get("rating", 0)),
        "review_count":    int(data.get("review_count", 0)),
        "has_website":     bool(data.get("website", "")),
        "found_at":        _now(),
        "status":          "unscored",
        "score":            0,
        "priority":         "",
        "score_reason":     "",
        "brand_gap":        "",
        "outreach_subject": "",
        "linkedin_note":    "",
        "decision_maker":       data.get("decision_maker", ""),
        "decision_maker_title": data.get("decision_maker_title", ""),
        "contact_email":        data.get("contact_email", ""),
        "linkedin_url":         data.get("linkedin_url", ""),
        "linkedin_owner":       "",
        "email_path":       None,
        "date_added":       _today(),
        "date_scored":      None,
        "date_sent":        None,
        "notes":            data.get("notes", ""),
        "is_favorite":      _truthy(data.get("is_favorite", False)),
        "favorite_note":    data.get("favorite_note", ""),
        "favorited_at":     _now() if _truthy(data.get("is_favorite", False)) else None,
        "favorite_order":   _next_favorite_order(_load()) if _truthy(data.get("is_favorite", False)) else None,
        "service_focus":     _normalize_choice(data.get("service_focus"), SERVICE_FOCUS_LABELS, "branding"),
        "service_mix":       _normalize_choice(data.get("service_mix"), SERVICE_MIX_LABELS, "smart_mix"),
        "primary_service":   _normalize_choice(data.get("primary_service") or data.get("service_focus"), SERVICE_OFFER_LABELS, "branding"),
        "secondary_services": data.get("secondary_services", []),
        "search_mode":       _normalize_choice(data.get("search_mode"), SEARCH_MODE_LABELS, "direct_client"),
        "market_preset":     _normalize_choice(data.get("market_preset"), MARKET_PRESETS, "premium_global"),
        "partner_lane":      _truthy(data.get("partner_lane", False)),
        "exclude_motion":    _truthy(data.get("exclude_motion", True)),
        "search_query":      data.get("search_query", ""),
        "search_location":   data.get("search_location", data.get("region", "")),
        "source_industry":   data.get("source_industry", industry),
        # Enrichment
        "enriched_at":        None,
        "website_summary":    None,
        "brand_signals":      None,
        "contact_page_email": None,
    }
    _ensure_fields(lead)

    prospects = _load()
    prospects.append(lead)
    _save(prospects)
    return jsonify({"lead": lead}), 201


@app.route("/api/leads/<lead_id>", methods=["PATCH"])
def api_update_lead(lead_id):
    prospects = _load()
    lead = _find(prospects, lead_id)
    if not lead:
        return jsonify({"error": "Lead not found"}), 404

    data = request.get_json(force=True)
    allowed = {
        "status", "notes", "outreach_subject", "outreach_draft", "brand_gap", "score_reason",
        "contact_email", "decision_maker", "decision_maker_title",
        "linkedin_url", "linkedin_note", "linkedin_owner", "email_path",
        "date_sent", "contact_page_email", "linkedin_profiles",
        "email_variants", "trigger", "ai_addon", "ai_addon_enabled",
        "variant_sent_index", "variant_sent_label", "variant_sent_approach",
        "variant_sent_subject", "send_channel", "date_replied",
        "reply_type", "reply_notes",
        "contact_candidates", "linkedin_candidates",
        "enrichment_status", "enrichment_audit",
        "is_favorite", "favorite_note", "favorited_at", "favorite_order",
        "service_focus", "service_mix", "primary_service", "secondary_services",
        "search_mode", "market_preset", "partner_lane",
        "exclude_motion", "search_query", "search_location", "source_industry",
    }
    for key in allowed:
        if key in data:
            lead[key] = data[key]
    _ensure_fields(lead)

    if "is_favorite" in data or "favorite_note" in data:
        lead["is_favorite"] = _truthy(lead.get("is_favorite"))
        if lead["is_favorite"]:
            if not lead.get("favorited_at"):
                lead["favorited_at"] = _now()
            if not lead.get("favorite_order"):
                lead["favorite_order"] = _next_favorite_order(prospects)
        else:
            lead["favorited_at"] = None
            lead["favorite_order"] = None

    sync_selected_candidates(lead)
    lead["enrichment_audit"] = audit_lead(lead)
    if any(key in data for key in ("outreach_subject", "outreach_draft", "email_variants", "trigger")):
        lead["tone_audit"] = audit_email_tone(lead)
    _save(prospects)
    return jsonify({"lead": lead})


@app.route("/api/leads/<lead_id>", methods=["DELETE"])
def api_delete_lead(lead_id):
    prospects = _load()
    lead = _find(prospects, lead_id)
    if not lead:
        return jsonify({"error": "Lead not found"}), 404

    prospects = [p for p in prospects if p["id"] != lead_id]
    _save(prospects)
    return jsonify({"ok": True})


# ---------------------------------------------------------------------------
# API: Search Google Places
# ---------------------------------------------------------------------------

@app.route("/api/search", methods=["POST"])
def api_search():
    data = request.get_json(force=True)
    industry = data.get("industry", "")
    location = data.get("location", "").strip()
    try:
        limit = int(data.get("limit", DEFAULT_LIMIT))
    except (TypeError, ValueError):
        limit = DEFAULT_LIMIT
    limit = max(1, min(limit, MAX_LIMIT))
    custom_query = data.get("query", "").strip()
    service_focus = _normalize_choice(data.get("service_focus"), SERVICE_FOCUS_LABELS, "branding")
    search_mode = _normalize_choice(
        data.get("search_mode") or ("agency_partner" if _truthy(data.get("partner_lane")) else ""),
        SEARCH_MODE_LABELS,
        "direct_client",
    )

    if not location:
        return jsonify({"error": "Location is required"}), 400

    query = custom_query or INDUSTRY_QUERIES.get(industry, industry)
    if not query:
        presets = SERVICE_SEARCH_PRESETS.get(service_focus, {}).get(search_mode, [])
        if presets:
            industry = presets[0]["industry"]
            query = presets[0]["query"]
    if not query:
        return jsonify({"error": "Industry or custom query is required"}), 400
    context = _prospecting_context(data, industry=industry, query=query, location=location)

    from sources.google_places import search as gp_search

    try:
        results = gp_search(query=query, location=location,
                            industry=industry, limit=limit)
    except (EnvironmentError, RuntimeError) as e:
        return jsonify({"error": str(e)}), 502

    filtered_motion = 0
    if context["exclude_motion"]:
        kept = []
        for lead in results:
            if _motion_focused(lead):
                filtered_motion += 1
                continue
            kept.append(lead)
        results = kept

    # Deduplicate against existing prospects
    prospects = _load()
    existing_ids = {p["id"] for p in prospects}
    new_leads = [r for r in results if r["id"] not in existing_ids]
    duplicate_count = len(results) - len(new_leads)

    for lead in new_leads:
        lead.update(context)
        lead["status"] = "unscored"

    # Enrich each new lead (best-effort, inline)
    for lead in new_leads:
        try:
            enrich_lead(lead)
            if context["exclude_motion"] and _motion_focused(lead):
                lead["motion_excluded"] = True
                lead["notes"] = "Motion graphics excluded from current prospecting focus."
        except Exception as e:
            print(f"[search] enrichment error for {lead.get('name')}: {e}")

    if context["exclude_motion"]:
        before = len(new_leads)
        new_leads = [lead for lead in new_leads if not lead.get("motion_excluded")]
        filtered_motion += before - len(new_leads)

    prospects.extend(new_leads)
    _save(prospects)

    resp = {
        "found": len(results),
        "added": len(new_leads),
        "duplicates": duplicate_count,
        "filtered_motion": filtered_motion,
        "service_focus": context["service_focus"],
        "service_focus_label": context["service_focus_label"],
        "service_mix": context["service_mix"],
        "service_mix_label": context["service_mix_label"],
        "primary_service": context["primary_service"],
        "primary_service_label": context["primary_service_label"],
        "secondary_services": context["secondary_services"],
        "secondary_service_labels": context["secondary_service_labels"],
        "outreach_angle": context["outreach_angle"],
        "search_mode": context["search_mode"],
        "search_mode_label": context["search_mode_label"],
    }
    if len(results) < limit:
        resp["note"] = f"Google Maps only found {len(results)} matching businesses for this search."
    return jsonify(resp)


# ---------------------------------------------------------------------------
# API: Score export / import
# ---------------------------------------------------------------------------

@app.route("/api/score/export", methods=["POST"])
def api_score_export():
    prospects = [_ensure_fields(p) for p in _load()]
    unscored = [p for p in prospects if not p.get("score") and p.get("status") not in ("skip",)]

    if not unscored:
        return jsonify({"error": "No unscored leads to export", "count": 0}), 200

    export = []
    for p in unscored:
        review_count = p.get("review_count", 0) or 0
        rating = p.get("rating", 0) or 0
        review_signal = (
            "Brand new (no reviews)" if review_count < 5
            else f"Established ({review_count} reviews, {rating})"
        )
        export.append({
            "id":            p["id"],
            "name":          p["name"],
            "industry":      p.get("industry", ""),
            "niche":         p.get("niche", ""),
            "city":          p.get("city", ""),
            "country":       p.get("country", ""),
            "region":        p.get("region", ""),
            "website":       p.get("website") or "NONE",
            "phone":         p.get("phone") or "NONE",
            "rating":        rating,
            "review_count":  review_count,
            "review_signal": review_signal,
            "google_maps_url": p.get("google_maps_url", ""),
            # Prospecting context
            "service_focus":       p.get("service_focus", "branding"),
            "service_focus_label": p.get("service_focus_label", _service_label(p.get("service_focus", "branding"))),
            "service_mix":         p.get("service_mix", "smart_mix"),
            "service_mix_label":   p.get("service_mix_label", _mix_label(p.get("service_mix", "smart_mix"))),
            "primary_service":     p.get("primary_service", p.get("service_focus", "branding")),
            "primary_service_label": p.get("primary_service_label", _offer_label(p.get("primary_service", p.get("service_focus", "branding")))),
            "secondary_services":  p.get("secondary_services", []),
            "secondary_service_labels": p.get("secondary_service_labels", _secondary_service_labels(p.get("secondary_services", []))),
            "outreach_angle":      p.get("outreach_angle", ""),
            "service_guidance":    _service_guidance(
                p.get("primary_service", p.get("service_focus", "branding")),
                p.get("secondary_services", []),
                p.get("service_mix", "smart_mix"),
            ),
            "search_mode":         p.get("search_mode", "direct_client"),
            "search_mode_label":   p.get("search_mode_label", _mode_label(p.get("search_mode", "direct_client"))),
            "market_preset":       p.get("market_preset", "premium_global"),
            "partner_lane":        _truthy(p.get("partner_lane")),
            "exclude_motion":      _truthy(p.get("exclude_motion", True)),
            "search_query":        p.get("search_query", ""),
            "search_location":     p.get("search_location", ""),
            "source_industry":     p.get("source_industry", p.get("industry", "")),
            "scoring_context": (
                "Agency Partner lane: score for overflow or collaboration fit. Do not criticize the agency's own branding. "
                "Prioritize boutique agencies, broad service menus, strong clients, small teams, and no obvious in-house brand identity specialist. "
                f"Service mix: {p.get('service_mix_label', _mix_label(p.get('service_mix', 'smart_mix')))}."
                if p.get("search_mode") == "agency_partner"
                else (
                    "Direct Client lane: score for visible need and commercial fit. "
                    f"Service mix: {p.get('service_mix_label', _mix_label(p.get('service_mix', 'smart_mix')))}. "
                    f"{_service_guidance(p.get('primary_service', p.get('service_focus', 'branding')), p.get('secondary_services', []), p.get('service_mix', 'smart_mix'))}"
                )
            ),
            # Enrichment fields for improved scoring
            "website_summary":   p.get("website_summary"),
            "brand_signals":     p.get("brand_signals"),
            "company_size":      p.get("company_size"),
            "industry_apollo":   p.get("industry_apollo"),
            "founded_year":      p.get("founded_year"),
            "estimated_revenue": p.get("estimated_revenue"),
            "apollo_keywords":   p.get("apollo_keywords", []),
        })

    path = os.path.join(DATA_DIR, "to_score.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(export, f, indent=2, ensure_ascii=False)

    return jsonify({"count": len(export), "path": path})


@app.route("/api/score/import", methods=["POST"])
def api_score_import():
    path = os.path.join(DATA_DIR, "scored.json")
    if not os.path.exists(path):
        return jsonify({
            "error": "data/scored.json not found. Ask Claude Code to score your prospects first."
        }), 404

    with open(path, "r", encoding="utf-8-sig") as f:
        scored_text = f.read()
    scored = json.loads(scored_text)
    log_api_usage(
        provider="codex_estimate",
        endpoint="score_import",
        status="ok",
        result_count=len(scored),
        estimated_tokens=_estimate_tokens_from_text(scored_text),
    )

    prospects = _load()
    updated = hot = warm = cold = skip_count = 0

    score_map = {s["id"]: s for s in scored}
    for p in prospects:
        if p["id"] in score_map:
            s = score_map[p["id"]]
            p["score"]          = int(s.get("score", 0))
            p["priority"]       = s.get("priority", "")
            p["score_reason"]   = s.get("score_reason", "")
            p["brand_gap"]      = s.get("brand_gap", "")
            p["outreach_subject"] = s.get("outreach_subject", "")
            p["linkedin_note"]  = s.get("linkedin_note", "")
            p["date_scored"]    = _today()
            # Set status based on priority, but never downgrade a lead that has
            # already progressed past scoring (drafted/sent/replied/...).
            priority = p["priority"]
            current = p.get("status", "")
            scoreable = current in ("", "unscored", "hot", "warm", "cold", "skip")
            if priority == "hot":
                if scoreable:
                    p["status"] = "hot"
                hot += 1
            elif priority == "warm":
                if scoreable:
                    p["status"] = "warm"
                warm += 1
            elif priority == "cold":
                if scoreable:
                    p["status"] = "cold"
                cold += 1
            else:
                if scoreable:
                    p["status"] = "skip"
                skip_count += 1
            updated += 1

    _save(prospects)

    # Archive the scored file
    archive = path.replace(".json", f"_{_now().replace(':', '-')}.json")
    os.rename(path, archive)

    return jsonify({
        "updated": updated,
        "hot": hot,
        "warm": warm,
        "cold": cold,
        "skip": skip_count,
    })


# ---------------------------------------------------------------------------
# API: Update status
# ---------------------------------------------------------------------------

@app.route("/api/update-status", methods=["POST"])
def api_update_status():
    data = request.get_json(force=True)
    lead_id = data.get("id", "").strip()
    new_status = data.get("status", "").strip()

    valid_statuses = {
        "unscored", "hot", "warm", "cold", "skip",
        "drafted", "sent", "bounced", "follow-up", "replied", "meeting", "converted",
    }
    if not lead_id:
        return jsonify({"error": "id is required"}), 400
    if new_status not in valid_statuses:
        return jsonify({"error": f"Invalid status. Must be one of: {', '.join(sorted(valid_statuses))}"}), 400

    prospects = _load()
    lead = _find(prospects, lead_id)
    if not lead:
        return jsonify({"error": "Lead not found"}), 404

    lead["status"] = new_status
    if new_status == "sent":
        variant_index = data.get("variant_index")
        try:
            variant_index = int(variant_index) if variant_index not in (None, "") else None
        except (TypeError, ValueError):
            variant_index = None
        _record_sent(lead, variant_index=variant_index, channel=data.get("channel", ""))
    elif data.get("clear_sent"):
        _clear_sent_record(lead)
    if new_status == "replied":
        _record_reply(
            lead,
            reply_type=data.get("reply_type", lead.get("reply_type", "")),
            reply_notes=data.get("reply_notes", lead.get("reply_notes", "")),
        )

    # Keep email-log.md in sync for post-send lifecycle changes.
    if new_status in ("sent", "bounced", "replied", "meeting", "converted"):
        note = ""
        if new_status == "replied":
            note = f"replied {_today()}" + (f": {lead.get('reply_type')}" if lead.get("reply_type") else "")
        elif new_status in ("meeting", "converted"):
            note = f"{new_status} {_today()}"
        _update_email_log_status(lead, new_status, note=note)

    _save(prospects)
    return jsonify({"lead": lead})


# ---------------------------------------------------------------------------
# API: Update notes
# ---------------------------------------------------------------------------

@app.route("/api/update-notes", methods=["POST"])
def api_update_notes():
    data = request.get_json(force=True)
    lead_id = data.get("id", "").strip()
    notes = data.get("notes", "")

    if not lead_id:
        return jsonify({"error": "id is required"}), 400

    prospects = _load()
    lead = _find(prospects, lead_id)
    if not lead:
        return jsonify({"error": "Lead not found"}), 404

    lead["notes"] = notes
    _save(prospects)
    return jsonify({"lead": lead})


# ---------------------------------------------------------------------------
# API: Export to Score (alias for frontend button)
# ---------------------------------------------------------------------------

@app.route("/api/export-to-score", methods=["POST"])
def api_export_to_score():
    return api_score_export()


# ---------------------------------------------------------------------------
# API: Import Scores (alias for frontend button)
# ---------------------------------------------------------------------------

@app.route("/api/import-scores", methods=["POST"])
def api_import_scores():
    return api_score_import()


# ---------------------------------------------------------------------------
# API: CSV Export
# ---------------------------------------------------------------------------

@app.route("/api/export/csv", methods=["POST"])
def api_export_csv():
    prospects = _load()
    data = request.get_json(force=True) if request.data else {}
    status_filter = data.get("status")

    leads = prospects
    if status_filter:
        leads = [p for p in leads if p.get("status") == status_filter]

    if not leads:
        return jsonify({"error": "No leads to export"}), 200

    os.makedirs(EXPORTS_DIR, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"outreachiq_{ts}.csv"
    filepath = os.path.join(EXPORTS_DIR, filename)

    columns = [
        "name", "industry", "city", "country", "website", "phone",
        "rating", "review_count", "score", "priority", "score_reason",
        "brand_gap", "outreach_subject", "status", "contact_email",
        "decision_maker", "linkedin_url", "date_added", "date_scored",
        "date_sent", "google_maps_url", "notes",
    ]

    with open(filepath, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(leads)

    return jsonify({"path": filepath, "count": len(leads), "filename": filename})


@app.route("/api/export/full-csv", methods=["POST"])
def api_export_full_csv():
    """Export every field including email draft and LinkedIn profiles (flattened)."""
    prospects = _load()
    if not prospects:
        return jsonify({"error": "No leads to export"}), 200

    # Flatten linkedin_profiles into up to 3 sets of columns
    def flatten(p):
        profiles = p.get("linkedin_profiles") or []
        row = {
            "name":             p.get("name", ""),
            "niche":            p.get("niche", "") or p.get("industry", ""),
            "industry":         p.get("industry", ""),
            "address":          p.get("address", ""),
            "city":             p.get("city", ""),
            "country":          p.get("country", ""),
            "website":          p.get("website", ""),
            "phone":            p.get("phone", ""),
            "rating":           p.get("rating", ""),
            "review_count":     p.get("review_count", ""),
            "status":           p.get("status", ""),
            "score":            p.get("score", ""),
            "priority":         p.get("priority", ""),
            "score_reason":     p.get("score_reason", ""),
            "brand_gap":        p.get("brand_gap", ""),
            "contact_email":    p.get("contact_email", ""),
            "decision_maker":   p.get("decision_maker", ""),
            "decision_maker_title": p.get("decision_maker_title", ""),
            "outreach_subject": p.get("outreach_subject", ""),
            "outreach_draft":   p.get("outreach_draft", ""),
            "linkedin_note":    p.get("linkedin_note", ""),
            "google_maps_url":  p.get("google_maps_url", ""),
            "date_added":       p.get("date_added", ""),
            "date_scored":      p.get("date_scored", ""),
            "date_sent":        p.get("date_sent", ""),
            "variant_sent_label": p.get("variant_sent_label", ""),
            "variant_sent_approach": p.get("variant_sent_approach", ""),
            "variant_sent_subject": p.get("variant_sent_subject", ""),
            "send_channel":     p.get("send_channel", ""),
            "reply_type":       p.get("reply_type", ""),
            "reply_notes":      p.get("reply_notes", ""),
            "date_replied":     p.get("date_replied", ""),
            "notes":            p.get("notes", ""),
        }
        for i in range(3):
            prefix = f"li_{i+1}_"
            if i < len(profiles):
                pr = profiles[i]
                row[prefix + "name"]             = pr.get("name", "")
                row[prefix + "title"]            = pr.get("title", "")
                row[prefix + "url"]              = pr.get("url", "")
                row[prefix + "connection_note"]  = pr.get("note", "")
                row[prefix + "follow_up"]        = pr.get("follow_up", "")
            else:
                row[prefix + "name"]             = ""
                row[prefix + "title"]            = ""
                row[prefix + "url"]              = ""
                row[prefix + "connection_note"]  = ""
                row[prefix + "follow_up"]        = ""
        return row

    rows = [flatten(p) for p in prospects]

    columns = [
        "name", "niche", "industry", "address", "city", "country",
        "website", "phone", "rating", "review_count",
        "status", "score", "priority", "score_reason", "brand_gap",
        "contact_email", "decision_maker", "decision_maker_title",
        "outreach_subject", "outreach_draft", "linkedin_note",
        "li_1_name", "li_1_title", "li_1_url", "li_1_connection_note", "li_1_follow_up",
        "li_2_name", "li_2_title", "li_2_url", "li_2_connection_note", "li_2_follow_up",
        "li_3_name", "li_3_title", "li_3_url", "li_3_connection_note", "li_3_follow_up",
        "google_maps_url", "date_added", "date_scored", "date_sent",
        "variant_sent_label", "variant_sent_approach", "variant_sent_subject", "send_channel",
        "reply_type", "reply_notes", "date_replied", "notes",
    ]

    os.makedirs(EXPORTS_DIR, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"outreachiq_full_{ts}.csv"
    filepath = os.path.join(EXPORTS_DIR, filename)

    with open(filepath, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)

    return jsonify({"path": filepath, "count": len(rows), "filename": filename})


@app.route("/api/export/download/<filename>")
def api_export_download(filename):
    filepath = os.path.join(EXPORTS_DIR, filename)
    if not os.path.exists(filepath):
        return jsonify({"error": "File not found"}), 404
    with open(filepath, "r", encoding="utf-8-sig") as f:
        content = f.read()
    return Response(
        content,
        mimetype="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )


# ---------------------------------------------------------------------------
# API: Email export / import
# ---------------------------------------------------------------------------

REPAIR_ACTIONS = {
    "fix_greeting": "Fix the greeting only. Use the confirmed first name if available. If no person is confirmed, use Hi team.",
    "make_specific": "Make this variant more specific. Add one concrete evidence point from enrichment, website, reviews, LinkedIn, Google, or snapshots.",
    "remove_ai": "Remove or soften the AI angle. Lead with taste, trust, positioning, client perception, and brand clarity.",
    "shorten": "Shorten this variant under 80 words while preserving the strongest concrete observation and soft CTA.",
    "regenerate_variant": "Rewrite this variant from scratch using the same approach, subject strategy, and tone rules.",
}


def _email_export_record(p: dict) -> dict:
    p = _ensure_fields(p)
    return {
        "id":              p["id"],
        "name":            p["name"],
        "industry":        p.get("industry", ""),
        "niche":           p.get("niche", ""),
        "city":            p.get("city", ""),
        "country":         p.get("country", ""),
        "website":         p.get("website") or "NONE",
        "score":           p.get("score", 0),
        "priority":        p.get("priority", ""),
        "score_reason":    p.get("score_reason", ""),
        "brand_gap":       p.get("brand_gap", ""),
        "outreach_subject": p.get("outreach_subject", ""),
        "contact_email":   p.get("contact_email", "") or p.get("contact_page_email", ""),
        "decision_maker":  p.get("decision_maker", ""),
        "decision_maker_title": p.get("decision_maker_title", ""),
        "linkedin_url":    p.get("linkedin_url", ""),
        "google_maps_url": p.get("google_maps_url", ""),
        "phone":           p.get("phone", ""),
        "rating":          p.get("rating", 0),
        "review_count":    p.get("review_count", 0),
        # Prospecting context for choosing the right outreach angle
        "service_focus":       p.get("service_focus", "branding"),
        "service_focus_label": p.get("service_focus_label", _service_label(p.get("service_focus", "branding"))),
        "service_mix":         p.get("service_mix", "smart_mix"),
        "service_mix_label":   p.get("service_mix_label", _mix_label(p.get("service_mix", "smart_mix"))),
        "primary_service":     p.get("primary_service", p.get("service_focus", "branding")),
        "primary_service_label": p.get("primary_service_label", _offer_label(p.get("primary_service", p.get("service_focus", "branding")))),
        "secondary_services":  p.get("secondary_services", []),
        "secondary_service_labels": p.get("secondary_service_labels", _secondary_service_labels(p.get("secondary_services", []))),
        "service_guidance":    _service_guidance(
            p.get("primary_service", p.get("service_focus", "branding")),
            p.get("secondary_services", []),
            p.get("service_mix", "smart_mix"),
        ),
        "search_mode":         p.get("search_mode", "direct_client"),
        "search_mode_label":   p.get("search_mode_label", _mode_label(p.get("search_mode", "direct_client"))),
        "market_preset":       p.get("market_preset", "premium_global"),
        "partner_lane":        _truthy(p.get("partner_lane")),
        "search_query":        p.get("search_query", ""),
        "search_location":     p.get("search_location", ""),
        "outreach_angle": p.get("outreach_angle") or _outreach_angle_for(
            primary_service=p.get("primary_service", p.get("service_focus", "branding")),
            secondary_services=p.get("secondary_services", []),
            search_mode=p.get("search_mode", "direct_client"),
            partner_lane=_truthy(p.get("partner_lane")),
            service_mix=p.get("service_mix", "smart_mix"),
        ),
        # Enrichment fields for improved email writing
        "website_summary":    p.get("website_summary"),
        "brand_signals":      p.get("brand_signals"),
        "contact_page_email":  p.get("contact_page_email", ""),
        "contact_page_emails": p.get("contact_page_emails", []),
        "company_size":       p.get("company_size"),
        "industry_apollo":    p.get("industry_apollo"),
        "founded_year":       p.get("founded_year"),
        "estimated_revenue":  p.get("estimated_revenue"),
        "apollo_keywords":    p.get("apollo_keywords", []),
        "apollo_linkedin_url": p.get("apollo_linkedin_url", ""),
    }


@app.route("/api/email/export", methods=["POST"])
def api_email_export():
    """Write data/to_write.json for leads that need emails written by Claude Code."""
    prospects = [_ensure_fields(p) for p in _load()]
    data = request.get_json(force=True) if request.data else {}
    ids = data.get("ids")  # Optional list of specific IDs (for single-lead regenerate)
    include_cold = bool(data.get("include_cold", False))

    if ids:
        to_write = [p for p in prospects if p["id"] in ids]
    else:
        allowed_priorities = ("hot", "warm", "cold") if include_cold else ("hot", "warm")
        # Export hot/warm leads by default. Cold leads require an explicit include_cold flag.
        to_write = [
            p for p in prospects
            if p.get("priority") in allowed_priorities
            and not p.get("email_variants")
            and not p.get("outreach_draft")
        ]

    if not to_write:
        return jsonify({"error": "No leads ready for email writing", "count": 0}), 200

    export = [_email_export_record(p) for p in to_write]

    path = os.path.join(DATA_DIR, "to_write.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(export, f, indent=2, ensure_ascii=False)

    # --- Duplicate contact email checks ---
    warnings = []

    # 1. Duplicates within this batch
    from collections import defaultdict
    email_to_names = defaultdict(list)
    for p in export:
        email = (p.get("contact_email") or "").strip().lower()
        if email:
            email_to_names[email].append(p["name"])
    for email, names in email_to_names.items():
        if len(names) > 1:
            warnings.append(
                f"Same email ({email}) on {len(names)} leads in this batch: {', '.join(names)}"
            )

    # 2. Email already used on a previously contacted lead
    contacted_statuses = {"sent", "follow-up", "replied", "meeting", "converted"}
    contacted_emails = {
        (p.get("contact_email") or "").strip().lower()
        for p in prospects
        if p.get("status") in contacted_statuses and p.get("contact_email")
    }
    export_ids = {p["id"] for p in export}
    for p in export:
        email = (p.get("contact_email") or "").strip().lower()
        if email and email in contacted_emails:
            # Find the already-contacted lead name
            already = next(
                (x["name"] for x in prospects
                 if (x.get("contact_email") or "").strip().lower() == email
                 and x.get("status") in contacted_statuses
                 and x["id"] not in export_ids),
                "another lead"
            )
            warnings.append(
                f"{p['name']}: {email} was already used on '{already}' (status: {next((x.get('status') for x in prospects if (x.get('contact_email') or '').strip().lower() == email and x.get('status') in contacted_statuses), '')})"
            )

    return jsonify({"count": len(export), "path": path, "warnings": warnings})


@app.route("/api/email/repair-export", methods=["POST"])
def api_email_repair_export():
    """Write data/to_write.json for one focused variant repair."""
    prospects = _load()
    data = request.get_json(force=True) if request.data else {}
    lead_id = (data.get("id") or data.get("lead_id") or "").strip()
    action = (data.get("action") or "regenerate_variant").strip()

    if not lead_id:
        return jsonify({"error": "id is required"}), 400
    if action not in REPAIR_ACTIONS:
        return jsonify({"error": f"Invalid repair action. Must be one of: {', '.join(sorted(REPAIR_ACTIONS))}"}), 400

    lead = _find(prospects, lead_id)
    if not lead:
        return jsonify({"error": "Lead not found"}), 404
    lead = _ensure_fields(lead)

    try:
        variant_index = int(data.get("variant_index", 0))
    except (TypeError, ValueError):
        return jsonify({"error": "variant_index must be a number"}), 400

    existing_variants = lead.get("email_variants") or []
    if existing_variants:
        if variant_index < 0 or variant_index >= len(existing_variants):
            return jsonify({"error": "variant_index is out of range"}), 400
        target_variant = existing_variants[variant_index]
    elif lead.get("outreach_draft"):
        variant_index = 0
        target_variant = {
            "label": "single",
            "approach": "legacy",
            "subject": lead.get("outreach_subject", ""),
            "body": lead.get("outreach_draft", ""),
        }
    else:
        return jsonify({"error": "Lead has no email draft to repair"}), 400

    audit = audit_email_tone(lead)
    variant_checks = audit.get("variant_checks", [])
    target_check = next(
        (check for check in variant_checks if int(check.get("index", -1)) == variant_index),
        variant_checks[variant_index] if variant_index < len(variant_checks) else {},
    )

    export_record = _email_export_record(lead)
    export_record.update({
        "repair_mode": True,
        "repair_action": action,
        "repair_instruction": REPAIR_ACTIONS[action],
        "repair_variant_index": variant_index,
        "repair_variant": target_variant,
        "repair_variant_flags": target_check.get("flags", []),
        "existing_variants": existing_variants,
        "existing_outreach_subject": lead.get("outreach_subject", ""),
        "existing_outreach_draft": lead.get("outreach_draft", ""),
        "tone_audit": audit,
        "repair_output_contract": (
            "Write data/written.json with one entry for this id. If existing_variants is present, "
            "return exactly the same number of variants and replace only repair_variant_index. "
            "Preserve unchanged variants unless they must be adjusted for consistency. "
            "If there are no existing_variants, create exactly 3 v4 variants."
        ),
    })

    path = os.path.join(DATA_DIR, "to_write.json")
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump([export_record], f, indent=2, ensure_ascii=False)

    return jsonify({
        "count": 1,
        "path": path,
        "repair": {
            "lead_id": lead_id,
            "variant_index": variant_index,
            "action": action,
            "label": target_variant.get("label", "single"),
        },
        "note": "Local repair export, no API usage",
    })


@app.route("/api/email/bulk-repair", methods=["POST"])
def api_email_bulk_repair():
    """Create data/written.json with local repairs for all unsent drafts needing review."""
    prospects = [_ensure_fields(p) for p in _load()]
    data = request.get_json(force=True) if request.data else {}
    include_contacted = bool(data.get("include_contacted", False))
    priority_filter = data.get("priorities")
    priority_filter = {str(p).lower() for p in priority_filter} if isinstance(priority_filter, list) else None
    contacted_statuses = {"sent", "follow-up", "replied", "meeting", "converted"}

    candidates = []
    for p in prospects:
        status = str(p.get("status") or "").lower()
        priority = str(p.get("priority") or status).lower()
        if not (p.get("email_variants") or p.get("outreach_draft")):
            continue
        if status == "skip":
            continue
        if priority_filter and priority not in priority_filter and status not in priority_filter:
            continue
        if not include_contacted and status in contacted_statuses:
            continue
        candidates.append(p)

    phrase_counts = phrase_counts_for_leads(candidates)
    targets = []
    for p in candidates:
        audit = audit_email_tone(p, phrase_counts=phrase_counts)
        flags = _email_review_flags(p, audit)
        if flags or audit.get("status") != "strong":
            targets.append(p)

    repaired = []
    for lead in targets:
        entry = repair_written_entry(lead, phrase_counts=phrase_counts)
        if entry:
            repaired.append(entry)

    path = os.path.join(DATA_DIR, "written.json")
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(repaired, f, indent=2, ensure_ascii=False)

    still_missing_email = sum(1 for item in repaired if not item.get("contact_email"))
    return jsonify({
        "count": len(repaired),
        "path": path,
        "missing_email": still_missing_email,
        "note": "Local bulk repair, no API usage. Click Import Emails to apply.",
    })


@app.route("/api/email/import", methods=["POST"])
def api_email_import():
    """Read data/written.json, merge email variants and LinkedIn profiles into prospects."""
    path = os.path.join(DATA_DIR, "written.json")
    if not os.path.exists(path):
        return jsonify({
            "error": "data/written.json not found. Ask Claude Code to write emails first."
        }), 404

    try:
        with open(path, "r", encoding="utf-8-sig") as f:
            written_text = f.read()
        written = json.loads(written_text)
    except json.JSONDecodeError as e:
        return jsonify({
            "error": f"Invalid JSON in data/written.json: {e.msg} at line {e.lineno}, column {e.colno}"
        }), 400
    log_api_usage(
        provider="codex_estimate",
        endpoint="email_import",
        status="ok",
        result_count=len(written),
        estimated_tokens=_estimate_tokens_from_text(written_text),
    )

    prospects = _load()
    updated = 0
    updated_leads = []
    tone_summary = None
    write_map = {w["id"]: w for w in written}

    for p in prospects:
        if p["id"] in write_map:
            w = write_map[p["id"]]

            # v4 variants
            if w.get("variants"):
                p["email_variants"] = w["variants"]
                # Backward compat: first variant becomes outreach_draft/subject
                p["outreach_draft"] = w.get("outreach_draft") or w["variants"][0].get("body", "")
                p["outreach_subject"] = w.get("outreach_subject") or w["variants"][0].get("subject", "")
            # v3 legacy sequence support
            elif w.get("sequence"):
                p["email_variants"] = w["sequence"]
                p["outreach_draft"] = w.get("outreach_draft") or (w["sequence"][0].get("body", "") if w["sequence"] else "")
                p["outreach_subject"] = w.get("outreach_subject") or (w["sequence"][0].get("subject", "") if w["sequence"] else "")
            else:
                if w.get("outreach_draft"):
                    p["outreach_draft"] = w["outreach_draft"]
                if w.get("outreach_subject"):
                    p["outreach_subject"] = w["outreach_subject"]

            if w.get("contact_email"):
                p["contact_email"] = w["contact_email"]
            if w.get("linkedin_profiles"):
                p["linkedin_profiles"] = w["linkedin_profiles"]
            if w.get("trigger"):
                p["trigger"] = w["trigger"]
            if w.get("ai_addon"):
                p["ai_addon"] = str(w["ai_addon"]).strip()
                p["ai_addon_enabled"] = True

            # Set status to drafted if email content was written
            has_email = w.get("variants") or w.get("sequence") or w.get("outreach_draft")
            if has_email and p.get("status") in ("hot", "warm", "cold"):
                p["status"] = "drafted"
            updated += 1
            updated_leads.append(p)

    if updated_leads:
        tone_summary = audit_many_email_tones(updated_leads)
        for p in updated_leads:
            p["tone_audit"] = tone_summary["audits_by_id"].get(p.get("id"), audit_email_tone(p))

    _save(prospects)

    # Archive the written file
    archive = path.replace(".json", f"_{_now().replace(':', '-')}.json")
    os.rename(path, archive)

    return jsonify({
        "updated": updated,
        "tone": tone_summary["counts"] if tone_summary else {"strong": 0, "needs_review": 0, "risky": 0},
    })


@app.route("/api/email/ai-addon-export", methods=["POST"])
def api_ai_addon_export():
    """Write data/to_ai_addon.json: a slim export of hot/warm leads that are not yet
    sent, so Claude can write one short optional AI add-on (a P.S.) per lead."""
    prospects = [_ensure_fields(p) for p in _load()]
    data = request.get_json(force=True) if request.data else {}
    ids = data.get("ids")
    include_existing = bool(data.get("include_existing", False))

    sent_statuses = {"sent", "replied", "meeting", "converted"}
    if ids:
        leads = [p for p in prospects if p["id"] in ids]
    else:
        leads = [
            p for p in prospects
            if p.get("priority") in ("hot", "warm")
            and p.get("status") not in sent_statuses
            and (include_existing or not (p.get("ai_addon") or "").strip())
        ]

    if not leads:
        return jsonify({"error": "No hot/warm unsent leads ready for an AI add-on", "count": 0}), 200

    export = []
    for p in leads:
        size = p.get("company_size")
        try:
            is_team = size is not None and int(size) > 1
        except (TypeError, ValueError):
            is_team = False
        niche = (p.get("niche") or p.get("industry") or "").lower()
        if not is_team and any(t in niche for t in ("agency", "team", "studio", "group")):
            is_team = True
        export.append({
            "id":              p["id"],
            "name":            p["name"],
            "niche":           p.get("niche", "") or p.get("industry", ""),
            "city":            p.get("city", ""),
            "company_size":    size,
            "audience":        "team" if is_team else "individual",
            "decision_maker":  p.get("decision_maker", ""),
            "trigger":         p.get("trigger", ""),
        })

    path = os.path.join(DATA_DIR, "to_ai_addon.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(export, f, indent=2, ensure_ascii=False)
    return jsonify({"count": len(export), "path": path})


@app.route("/api/email/ai-addon-import", methods=["POST"])
def api_ai_addon_import():
    """Read data/ai_addon.json and merge the optional AI add-on P.S. onto leads.
    Leaves the branding variants and lead status untouched."""
    path = os.path.join(DATA_DIR, "ai_addon.json")
    if not os.path.exists(path):
        return jsonify({
            "error": "data/ai_addon.json not found. Ask Claude Code to write AI add-ons first."
        }), 404
    try:
        with open(path, "r", encoding="utf-8-sig") as f:
            text = f.read()
        rows = json.loads(text)
    except json.JSONDecodeError as e:
        return jsonify({
            "error": f"Invalid JSON in data/ai_addon.json: {e.msg} at line {e.lineno}, column {e.colno}"
        }), 400

    prospects = _load()
    addon_map = {r["id"]: r for r in rows if isinstance(r, dict) and r.get("id")}
    updated = 0
    warnings = []
    for p in prospects:
        if p["id"] in addon_map:
            addon = (addon_map[p["id"]].get("ai_addon") or "").strip()
            if not addon:
                continue
            for issue in lint_ai_addon(addon):
                warnings.append(f"{p.get('name', p['id'])}: {issue}")
            p["ai_addon"] = addon
            p["ai_addon_enabled"] = True
            updated += 1

    _save(prospects)
    archive = path.replace(".json", f"_{_now().replace(':', '-')}.json")
    os.rename(path, archive)
    return jsonify({"updated": updated, "warnings": warnings})


@app.route("/api/email/ai-addon-bulk", methods=["POST"])
def api_ai_addon_bulk():
    """Enable or disable the AI add-on on every hot/warm lead that has add-on text."""
    data = request.get_json(force=True) if request.data else {}
    enabled = _truthy(data.get("enabled", True))
    ids = set(data.get("ids") or [])

    prospects = _load()
    updated = 0
    for p in prospects:
        if ids and p.get("id") not in ids:
            continue
        if p.get("priority") not in ("hot", "warm"):
            continue
        if not (p.get("ai_addon") or "").strip():
            continue
        if _truthy(p.get("ai_addon_enabled")) != enabled:
            p["ai_addon_enabled"] = enabled
            updated += 1

    _save(prospects)
    return jsonify({"updated": updated, "enabled": enabled})


@app.route("/api/enrichment/run", methods=["POST"])
def api_enrichment_run():
    """Run paid enrichment for selected leads, or hot/warm leads by default."""
    data = request.get_json(force=True) if request.data else {}
    ids = set(data.get("ids") or [])
    include_people = bool(data.get("include_people", False))
    force = bool(data.get("force", True))
    dry_run = bool(data.get("dry_run", False))
    limit_raw = data.get("limit", None)
    limit = int(limit_raw) if limit_raw is not None else None

    prospects = _load()
    if ids:
        targets = [p for p in prospects if p.get("id") in ids]
    else:
        targets = [p for p in prospects if p.get("priority") in ("hot", "warm")]
    if limit is not None:
        targets = targets[:max(limit, 0)]

    if dry_run:
        return jsonify({
            "would_update": len(targets),
            "include_people": include_people,
            "mode": "selected" if ids else "hot_warm_default",
        })

    updated = 0
    errors = []
    for lead in targets:
        try:
            enrich_lead(lead, force=force, include_people=include_people)
            updated += 1
        except Exception as e:
            errors.append({"id": lead.get("id"), "name": lead.get("name"), "error": str(e)})

    _save(prospects)
    return jsonify({
        "updated": updated,
        "errors": errors,
        "include_people": include_people,
        "mode": "selected" if ids else "hot_warm_default",
    })


# ---------------------------------------------------------------------------
# Bulk: find missing contact emails for drafted leads
# ---------------------------------------------------------------------------

@app.route("/api/email/find-missing-emails", methods=["POST"])
def api_find_missing_emails():
    """Re-enrich drafted leads with no contact_email and auto-promote a
    same-domain address so they become Gmail-sendable.

    Body (all optional):
      ids:     restrict to these lead ids
      limit:   cap how many leads to process (default 50; Firecrawl cost)
      dry_run: just report how many leads would be processed
    """
    data = request.get_json(silent=True) or {}
    ids = set(data.get("ids") or [])
    dry_run = bool(data.get("dry_run", False))
    limit_raw = data.get("limit", 50)
    limit = int(limit_raw) if limit_raw is not None else None

    prospects = _load()

    def _missing(p):
        return (
            p.get("status") == "drafted"
            and not (p.get("contact_email") or "").strip()
            and (p.get("website") or "").strip()
        )

    targets = [p for p in prospects if _missing(p) and (not ids or p.get("id") in ids)]

    if dry_run:
        return jsonify({"targets": len(targets), "total_missing": sum(1 for p in prospects if _missing(p))})

    if limit is not None:
        targets = targets[:max(limit, 0)]

    scanned = emails_found = promoted = 0
    errors = []
    for i, lead in enumerate(targets, 1):
        scanned += 1
        try:
            enrich_lead(lead, force=True, include_people=False)
            if (lead.get("contact_page_email") or lead.get("contact_page_emails")
                    or lead.get("contact_candidates")):
                emails_found += 1
            if promote_best_contact_email(lead):
                promoted += 1
                lead["tone_audit"] = audit_email_tone(lead)
        except Exception as e:
            errors.append({"id": lead.get("id"), "name": lead.get("name"), "error": str(e)})
        # Incremental save (crash-safety; OneDrive DB), like the send loop.
        if i % 10 == 0:
            _save(prospects)

    _save(prospects)
    still_missing = sum(1 for p in prospects if _missing(p))
    return jsonify({
        "scanned": scanned,
        "emails_found": emails_found,
        "promoted": promoted,
        "still_missing": still_missing,
        "errors": errors,
    })


# ---------------------------------------------------------------------------
# Scrape contact email from website
# ---------------------------------------------------------------------------

@app.route("/api/scrape-contact", methods=["POST"])
def scrape_contact():
    """Scrape website for email addresses. Uses Firecrawl when available, falls back to raw HTTP."""
    import re
    import requests as _requests
    data = request.json or {}
    website = (data.get("website") or "").strip()
    if not website:
        return jsonify({"error": "No website provided"}), 400
    if not website.startswith("http"):
        website = "https://" + website

    EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}")
    SKIP = {"example.com", "yourdomain", "noreply", "no-reply", "donotreply",
            "domain.com", "sentry", "w3.org", "schema.org", "google.com",
            "facebook.com", "instagram.com", "twitter.com", "wixpress.com",
            "squarespace.com", "shopify.com", "amazonaws.com"}

    def _filter_emails(raw_list):
        return sorted({
            e.lower() for e in raw_list
            if not any(s in e.lower() for s in SKIP) and is_valid_email(e)
        })

    # Common subpages where emails appear (including Norwegian variants)
    CONTACT_PATHS = [
        "", "/contact", "/contact-us", "/about", "/about-us",
        "/kontakt", "/om-oss", "/om", "/kontakt-oss",
        "/team", "/people", "/staff", "/our-team",
        "/footer", "/imprint", "/impressum",
        "/en/contact", "/en/about", "/en/about-us", "/en/team",
    ]

    base = website.rstrip("/")

    # Prefer Firecrawl (handles JS-rendered sites)
    if FIRECRAWL_API_KEY:
        try:
            from sources.firecrawl import scrape_website
            fc = scrape_website(website)
            if fc.get("contact_page_emails"):
                return jsonify({
                    "emails": fc["contact_page_emails"],
                    "contact_candidates": fc.get("contact_candidates", []),
                    "source": "firecrawl",
                })
        except Exception as e:
            print(f"[scrape-contact] Firecrawl path failed: {e}")

    # Fallback: raw HTTP requests across all common subpages
    headers = {"User-Agent": "Mozilla/5.0 (compatible; OutreachIQ/1.0)"}
    emails_found = set()
    for path in CONTACT_PATHS:
        url = base + path
        try:
            r = _requests.get(url, timeout=8, headers=headers, allow_redirects=True)
            if r.ok:
                for e in EMAIL_RE.findall(r.text):
                    if not any(skip in e.lower() for skip in SKIP):
                        emails_found.add(e.lower())
        except Exception:
            pass

    return jsonify({"emails": sorted(emails_found)})


# ---------------------------------------------------------------------------
# API: Re-enrich a single lead
# ---------------------------------------------------------------------------

@app.route("/api/enrich/<lead_id>", methods=["POST"])
def api_enrich_lead(lead_id):
    """Force re-enrich a single lead with Firecrawl + Apollo."""
    data = request.get_json(silent=True) or {}
    prospects = _load()
    lead = _find(prospects, lead_id)
    if not lead:
        return jsonify({"error": "Lead not found"}), 404

    try:
        enrich_lead(lead, force=True, include_people=bool(data.get("include_people", False)))
    except Exception as e:
        return jsonify({"error": f"Enrichment failed: {e}"}), 502

    _save(prospects)
    return jsonify({"lead": _ensure_fields(lead)})


# ---------------------------------------------------------------------------
# Background reply/bounce poller
# ---------------------------------------------------------------------------

def _reply_poll_loop():
    """While the server runs, pull replies/bounces from Gmail every
    REPLY_POLL_MINUTES. First pass 2 minutes after startup, so a freshly
    opened dashboard shows current data without clicking Check replies."""
    delay = 120
    while True:
        time.sleep(delay)
        delay = max(REPLY_POLL_MINUTES, 1) * 60
        try:
            from mailer import gmail_client
            if not gmail_client.is_configured():
                continue
            summary = _check_replies_core(gmail_client)
            if summary["new_replies"] or summary["new_bounces"]:
                print(f"[reply-poll] recorded {summary['new_replies']} replies, "
                      f"{summary['new_bounces']} bounces "
                      f"(checked {summary['checked']} threads)", flush=True)
        except Exception as e:
            print(f"[reply-poll] error: {e}", flush=True)


def _start_reply_poller():
    # With the Werkzeug reloader active, only the serving child process
    # (WERKZEUG_RUN_MAIN=true) should poll, or two threads would race.
    if REPLY_POLL_MINUTES <= 0:
        return
    if os.environ.get("WERKZEUG_RUN_MAIN") != "true":
        return
    threading.Thread(target=_reply_poll_loop, daemon=True, name="reply-poller").start()
    print(f"  Reply poller: every {REPLY_POLL_MINUTES} min (REPLY_POLL_MINUTES=0 disables)", flush=True)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    os.makedirs(DATA_DIR, exist_ok=True)
    os.makedirs(EXPORTS_DIR, exist_ok=True)
    os.makedirs(EMAILS_DIR, exist_ok=True)
    os.makedirs(ENRICHMENT_DIR, exist_ok=True)
    print("\n  OutreachIQ")
    print("  ----------")
    keys = validate_keys()
    for k, v in keys.items():
        icon = "OK" if v == "OK" else "MISSING"
        print(f"  {icon}: {k}")
    print(f"\n  Dashboard at http://localhost:5001\n")
    _start_reply_poller()
    app.run(debug=True, port=5001)
