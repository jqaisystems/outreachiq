"""Local tone audit helpers for OutreachIQ email drafts."""

from __future__ import annotations

import os
import re
from collections import Counter
from datetime import datetime, timezone
from urllib.parse import urlparse

# The sender's own domain: self-promotion links to it are flagged by the audit
# (the dashboard appends the signature, so links in the body read as pushy).
_SELF_DOMAIN = os.getenv("SIGNATURE_WEBSITE", "www.example.com").lower().removeprefix("https://").removeprefix("http://").removeprefix("www.")


SOFT_CTAS = {
    "is this something you've been thinking about?",
    "worth a conversation?",
    "is this on your radar?",
    "would that be useful?",
}

OVERUSED_PHRASES = [
    "i came across",
    "deserves a brand",
    "ai tools",
    "branding supported by practical ai tools",
    "the proof you already have",
    "has the ingredients",
    "useful proof",
    "first impression matches the quality",
]

# Permanently retired strings (2026-07-02 zero-replies diagnostic): these
# appeared verbatim across dozens of sent emails and fingerprint the sender.
# Unlike OVERUSED_PHRASES they flag on every occurrence, not at a batch
# threshold.
RETIRED_PHRASES = [
    "i came across",
    "caught my eye",
    "when brand projects pile up",
    "stood out through",
    "while researching",
    "just to understand where your brand is today",
    "would you be open to",
]

# Internal pipeline vocabulary that must never reach a prospect.
INTERNAL_VOCAB = [
    "the export shows",
    "the export",
    "no website surfaced",
    "surfaced",
    "the scrape",
    "enrichment",
]

# Agency-partner copy markers; only valid when the lead is a partner lead.
PARTNER_COPY_MARKERS = [
    "overflow",
    "when brand projects pile up",
    "white label",
    "white-label",
]

# Doubled merge clause, e.g. "caught my eye because the company caught my eye".
_DOUBLED_CLAUSE_RE = re.compile(r"\b(\w+\s+\w+\s+\w+)\b.{1,60}?\b\1\b", re.IGNORECASE)

# Non-Latin scripts leaking from enrichment fields (Arabic, Cyrillic, Hebrew, CJK).
_NON_LATIN_RE = re.compile(r"[Ѐ-ӿ֐-׿؀-ۿ぀-ヿ一-鿿]")

_REVIEW_COUNT_RE = re.compile(r"\b\d+\s+(?:google\s+)?(?:five[- ]star\s+)?reviews?\b", re.IGNORECASE)

BAD_GREETING_NAMES = {
    "a",
    "an",
    "the",
    "hotel",
    "interior",
    "athletic",
    "luxury",
    "real",
    "estate",
    "group",
    "company",
    "studio",
    "space",
    "design",
    "properties",
    "homes",
    "services",
}

COMPANY_STOPWORDS = {
    "a",
    "an",
    "the",
    "and",
    "of",
    "for",
    "by",
    "de",
    "di",
    "la",
    "le",
    "el",
    "group",
    "company",
    "co",
    "inc",
    "llc",
    "ltd",
    "gmbh",
    "ag",
    "as",
}

AI_SENSITIVE_TERMS = {
    "architecture",
    "architect",
    "real estate",
    "luxury",
    "hospitality",
    "hotel",
    "restaurant",
    "interior",
    "design",
}

FLAG_LABELS = {
    "bad_greeting": "Bad greeting",
    "company_fragment_greeting": "Company fragment greeting",
    "generic_greeting": "Generic greeting",
    "missing_greeting": "Missing greeting",
    "over_80_words": "Over 80 words",
    "dash_not_allowed": "Dash not allowed",
    "portfolio_in_body": "Portfolio in body",
    "credential_dump": "Credential dump",
    "hedge_phrase": "Hedge phrase",
    "hard_cta": "Hard CTA",
    "missing_soft_cta": "Missing soft CTA",
    "diagnosis_language": "Diagnosis language",
    "weak_evidence": "Weak evidence",
    "repeated_phrase": "Repeated phrase",
    "ai_overused": "AI overused",
    "ai_needs_fit": "AI needs fit",
    "old_single_draft": "Old single draft",
    "render_artifact": "Render artifact",
    "template_mismatch": "Template mismatch",
    "retired_phrase": "Retired phrase",
    "subject_template": "Overused subject template",
    "subject_truncated": "Truncated subject",
    "review_count_only": "Review count as only evidence",
    "clone_body": "Near-identical draft",
}

SEVERITY_RANK = {"strong": 0, "needs_review": 1, "risky": 2}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def word_count(text: str) -> int:
    return len(re.findall(r"\b[\w']+\b", text or ""))


AI_ADDON_MAX_WORDS = 45


def lint_ai_addon(text: str) -> list[str]:
    """Light checks for the optional AI add-on P.S. Returns a list of issue strings
    (empty when clean). It never blocks; the caller surfaces issues as warnings."""
    issues: list[str] = []
    body = text or ""
    if "—" in body or "–" in body:
        issues.append("contains an em or en dash; use commas, colons, or full stops")
    words = word_count(body)
    if words > AI_ADDON_MAX_WORDS:
        issues.append(f"{words} words; keep the add-on under {AI_ADDON_MAX_WORDS}")
    if re.search(r"\b(15[- ]?minute|book a call|schedule a|quick call|call make sense)\b", body, re.IGNORECASE):
        issues.append("reads like a meeting ask; keep it interest-based")
    return issues


def _flag(code: str, severity: str, detail: str = "") -> dict:
    return {
        "code": code,
        "label": FLAG_LABELS.get(code, code.replace("_", " ").title()),
        "severity": severity,
        "detail": detail,
    }


def _add_flag(flags: list[dict], code: str, severity: str, detail: str = "") -> None:
    key = (code, detail)
    if any((f.get("code"), f.get("detail", "")) == key for f in flags):
        return
    flags.append(_flag(code, severity, detail))


def _status_from_flags(flags: list[dict]) -> str:
    if any(f.get("severity") == "risky" for f in flags):
        return "risky"
    if any(f.get("severity") == "needs_review" for f in flags):
        return "needs_review"
    return "strong"


def _first_non_empty_line(text: str) -> str:
    for line in (text or "").splitlines():
        if line.strip():
            return line.strip()
    return ""


def _last_non_empty_line(text: str) -> str:
    for line in reversed((text or "").splitlines()):
        if line.strip():
            return line.strip()
    return ""


def _first_significant_company_token(name: str) -> str:
    for token in re.findall(r"[A-Za-z][A-Za-z']+", name or ""):
        lowered = token.lower()
        if lowered not in COMPANY_STOPWORDS:
            return lowered
    return ""


def _decision_first_names(lead: dict) -> set[str]:
    names = []
    if lead.get("decision_maker"):
        names.append(str(lead.get("decision_maker")))
    for profile in lead.get("linkedin_profiles") or []:
        if profile.get("name"):
            names.append(str(profile.get("name")))
    first_names = set()
    for name in names:
        token_match = re.search(r"[A-Za-z][A-Za-z']+", name)
        if token_match:
            first_names.add(token_match.group(0).lower())
    return first_names


def _domain_from_url(url: str) -> str:
    if not url:
        return ""
    parsed = urlparse(url if "://" in url else f"https://{url}")
    domain = (parsed.netloc or parsed.path).lower()
    return domain.replace("www.", "").split("/")[0]


def _mentions_ai(text: str) -> bool:
    return bool(re.search(r"\bai\b", text or "", re.IGNORECASE))


def _body_has_evidence(body: str, lead: dict) -> bool:
    lower = (body or "").lower()
    if re.search(r"\b(19|20)\d{2}\b", body or ""):
        return True
    if re.search(r"\b\d+(\.\d+)?\s*(reviews?|employees?|locations?|years?)\b", lower):
        return True
    if "review" in lower and str(lead.get("review_count") or "") in lower:
        return True

    review_count = lead.get("review_count")
    if review_count and str(review_count) in lower:
        return True
    founded_year = lead.get("founded_year")
    if founded_year and str(founded_year) in lower:
        return True
    company_size = lead.get("company_size")
    if company_size and str(company_size) in lower:
        return True

    domain = _domain_from_url(lead.get("website", ""))
    if domain and domain in lower:
        return True

    keywords = lead.get("apollo_keywords") or []
    for keyword in keywords:
        keyword = str(keyword).strip().lower()
        if len(keyword) >= 5 and keyword in lower:
            return True

    summary = str(lead.get("website_summary") or "")
    for token in re.findall(r"\b[A-Z][A-Za-z]{4,}\b", summary):
        if token.lower() in lower:
            return True

    return False


def _body_has_specific_evidence(body: str, lead: dict) -> bool:
    """Evidence beyond a Google review count: a year, company size, domain,
    keyword, or a proper noun from the website summary."""
    lower = (body or "").lower()
    if re.search(r"\b(19|20)\d{2}\b", body or ""):
        return True
    founded_year = lead.get("founded_year")
    if founded_year and str(founded_year) in lower:
        return True
    company_size = lead.get("company_size")
    if company_size and str(company_size) in lower:
        return True
    domain = _domain_from_url(lead.get("website", ""))
    if domain and domain in lower:
        return True
    for keyword in lead.get("apollo_keywords") or []:
        keyword = str(keyword).strip().lower()
        if len(keyword) >= 5 and keyword in lower:
            return True
    summary = str(lead.get("website_summary") or "")
    for token in re.findall(r"\b[A-Z][A-Za-z]{4,}\b", summary):
        if token.lower() in lower:
            return True
    return False


def _has_doubled_clause(body: str, lead: dict | None = None) -> str:
    """Detect a merge artifact where the same 3-word phrase repeats inside one
    sentence ("caught my eye because the company caught my eye"). Phrases
    containing company-name tokens are exempt: naming the company twice in a
    sentence is legitimate. Returns the repeated phrase or an empty string."""
    name_tokens = {t.lower() for t in re.findall(r"[\w']+", (lead or {}).get("name", ""))}
    for sentence in re.split(r"[.!?\n]", body or ""):
        words = re.findall(r"[\w']+", sentence.lower())
        seen: dict[tuple, int] = {}
        for i in range(len(words) - 2):
            gram = tuple(words[i:i + 3])
            if not any(len(w) >= 5 for w in gram):
                continue
            if name_tokens and any(w in name_tokens for w in gram):
                continue
            if gram in seen and i - seen[gram] >= 3:
                return " ".join(gram)
            seen.setdefault(gram, i)
    return ""


def _audit_render_artifacts(body: str, flags: list[dict], lead: dict | None = None) -> None:
    lower = (body or "").lower()
    for term in INTERNAL_VOCAB:
        if term in lower:
            _add_flag(flags, "render_artifact", "risky", f"Internal pipeline wording in the body: `{term}`.")
            break
    if _NON_LATIN_RE.search(body or ""):
        _add_flag(flags, "render_artifact", "risky", "Non-Latin script leaked into the body (check the city field).")
    doubled = _has_doubled_clause(body, lead)
    if doubled:
        _add_flag(flags, "render_artifact", "risky", f"Doubled clause: `{doubled}` repeats within one sentence.")


def _audit_subject(subject: str, lead: dict, flags: list[dict]) -> None:
    subj = (subject or "").strip()
    if not subj:
        return
    if subj.lower().startswith("quick thought on"):
        _add_flag(flags, "subject_template", "needs_review",
                  "Retired subject template. Write a subject with one lead-specific detail.")
    tokens = re.findall(r"[\w&+']+", subj)
    if len(subj) >= 38 and tokens:
        tail = tokens[-1].lower()
        name_tokens = [t.lower() for t in re.findall(r"[\w&+']+", lead.get("name", ""))]
        if len(tail) >= 2 and any(t.startswith(tail) and t != tail for t in name_tokens):
            _add_flag(flags, "subject_truncated", "risky",
                      f"Subject appears cut mid-word (`...{tokens[-1]}`). Shorten the phrase, keep the company name whole.")


def _audit_retired_phrases(subject: str, body: str, flags: list[dict]) -> None:
    haystack = f"{subject}\n{body}".lower()
    hits = [p for p in RETIRED_PHRASES if p in haystack]
    if hits:
        _add_flag(flags, "retired_phrase", "needs_review",
                  "Fingerprinted cold-email phrasing: " + ", ".join(f"`{h}`" for h in hits[:3]) + ". Rewrite in fresh words.")


def _audit_template_mismatch(body: str, lead: dict, flags: list[dict]) -> None:
    if lead.get("search_mode") == "agency_partner" or lead.get("partner_lane"):
        return
    lower = (body or "").lower()
    for marker in PARTNER_COPY_MARKERS:
        if marker in lower:
            _add_flag(flags, "template_mismatch", "risky",
                      f"Agency-partner copy (`{marker}`) on a direct-client lead.")
            return


def _extract_variants(lead: dict) -> tuple[str, list[dict]]:
    variants = lead.get("email_variants") or lead.get("variants") or []
    if variants:
        return "variants", [
            {
                "label": v.get("label") or chr(65 + i),
                "approach": v.get("approach") or v.get("type") or "",
                "subject": v.get("subject") or "",
                "body": v.get("body") or "",
            }
            for i, v in enumerate(variants)
        ]
    if lead.get("outreach_draft"):
        return "single", [{
            "label": "single",
            "approach": "legacy",
            "subject": lead.get("outreach_subject") or "",
            "body": lead.get("outreach_draft") or "",
        }]
    return "none", []


def _audit_greeting(body: str, lead: dict, flags: list[dict]) -> None:
    first_line = _first_non_empty_line(body)
    match = re.match(r"^Hi\s*([^,\n!]+)?[,!]", first_line, re.IGNORECASE)
    if not match:
        _add_flag(flags, "missing_greeting", "needs_review", "Use a confident first name or Hi team.")
        return

    greeting_name = (match.group(1) or "").strip()
    lowered = greeting_name.lower()
    if not greeting_name:
        _add_flag(flags, "missing_greeting", "needs_review", "Use a confident first name or Hi team.")
        return
    if lowered == "team":
        return
    if lowered == "there":
        _add_flag(flags, "generic_greeting", "needs_review", "Prefer Hi team when no person is confirmed.")
        return
    if lowered in BAD_GREETING_NAMES:
        _add_flag(flags, "bad_greeting", "risky", f"{greeting_name} looks like a company fragment.")
        return

    decision_first_names = _decision_first_names(lead)
    if lowered in decision_first_names:
        return

    first_company_token = _first_significant_company_token(lead.get("name", ""))
    if first_company_token and lowered == first_company_token:
        _add_flag(flags, "company_fragment_greeting", "needs_review", f"{greeting_name} may be the company name, not a person.")


def _audit_banned_style(body: str, flags: list[dict]) -> None:
    lower = (body or "").lower()
    if "\u2014" in body or "\u2013" in body:
        _add_flag(flags, "dash_not_allowed", "risky", "Use commas, colons, or full stops.")
    # Flag pushing the sender's own portfolio or links (the dashboard appends
    # those), not the client's own portfolio of work or a company name containing the word.
    if _SELF_DOMAIN in lower or re.search(
        r"\b(?:my|our)\s+portfolio\b"
        r"|\bportfolio\s+(?:link|attached|below)\b"
        r"|\b(?:see|view|check out|here'?s|link to|share)\s+(?:my|our)\s+portfolio\b",
        lower,
    ):
        _add_flag(flags, "portfolio_in_body", "risky", "Do not push your own portfolio or links; the dashboard appends them.")
    if re.search(r"\b12\+?\s+years\b|\b1,?200\+?\s+brands\b|\b40\+?\s+countries\b", lower):
        _add_flag(flags, "credential_dump", "risky", "Keep the self-intro tiny. Do not list years, brand counts, or countries.")
    if re.search(r"\bif (it'?s )?(useful|relevant|resonates|interesting)\b", lower) or "if you're curious" in lower:
        _add_flag(flags, "hedge_phrase", "needs_review", "Use a cleaner interest CTA.")
    if re.search(r"\b(15[- ]?minute|book a call|schedule|meeting|quick call|call make sense)\b", lower):
        _add_flag(flags, "hard_cta", "risky", "Cold email should not ask for a meeting upfront.")
    if re.search(r"\b(brand is weak|weak brand|looks weak|bad branding|poor branding|unprofessional)\b", lower):
        _add_flag(flags, "diagnosis_language", "risky", "Elevate the prospect instead of diagnosing them.")


def _audit_cta(body: str, flags: list[dict]) -> None:
    last_line = _last_non_empty_line(body)
    lowered = last_line.lower().strip()
    if lowered in SOFT_CTAS:
        return
    if re.search(r"\b(15[- ]?minute|book a call|schedule|meeting|quick call|call make sense)\b", lowered):
        _add_flag(flags, "hard_cta", "risky", "Use a low-friction interest CTA.")
        return
    if "?" not in last_line:
        _add_flag(flags, "missing_soft_cta", "needs_review", "End with a clear, low-friction question.")


def _audit_variant(
    lead: dict,
    variant: dict,
    index: int,
    phrase_counts: Counter | None = None,
    phrase_threshold: int = 3,
) -> dict:
    body = variant.get("body") or ""
    flags: list[dict] = []
    words = word_count(body)

    if words > 80:
        _add_flag(flags, "over_80_words", "needs_review", f"{words} words.")
    _audit_greeting(body, lead, flags)
    _audit_banned_style(body, flags)
    _audit_cta(body, flags)
    if body and not _body_has_evidence(body, lead):
        _add_flag(flags, "weak_evidence", "needs_review", "Add one concrete source-backed detail.")

    subject = variant.get("subject") or ""
    _audit_render_artifacts(body, flags, lead)
    _audit_subject(subject, lead, flags)
    _audit_retired_phrases(subject, body, flags)
    _audit_template_mismatch(body, lead, flags)
    if body and _REVIEW_COUNT_RE.search(body) and not _body_has_specific_evidence(body, lead):
        _add_flag(flags, "review_count_only", "needs_review",
                  "A review count is the only evidence. Add a project, client, award, or a line from their site.")

    lower = body.lower()
    if phrase_counts:
        for phrase in OVERUSED_PHRASES:
            count = phrase_counts.get(phrase, 0)
            if count >= phrase_threshold and phrase in lower:
                _add_flag(flags, "repeated_phrase", "needs_review", f"`{phrase}` appears {count} times in this draft set.")

    return {
        "index": index,
        "label": variant.get("label") or chr(65 + index),
        "approach": variant.get("approach") or "",
        "subject": variant.get("subject") or "",
        "word_count": words,
        "status": _status_from_flags(flags),
        "flags": flags,
    }


def _lead_needs_taste_first_ai(body: str, lead: dict) -> bool:
    if not _mentions_ai(body or ""):
        return False
    haystack = " ".join([
        str(lead.get("industry") or ""),
        str(lead.get("niche") or ""),
        str(lead.get("industry_apollo") or ""),
        str(lead.get("score_reason") or ""),
    ]).lower()
    return any(term in haystack for term in AI_SENSITIVE_TERMS)


def _aggregate_flags(variant_checks: list[dict]) -> list[dict]:
    counts = Counter()
    examples = {}
    severities = {}
    for check in variant_checks:
        for flag in check.get("flags", []):
            code = flag["code"]
            counts[code] += 1
            examples.setdefault(code, flag.get("detail", ""))
            severity = flag.get("severity", "needs_review")
            if SEVERITY_RANK.get(severity, 0) > SEVERITY_RANK.get(severities.get(code, "strong"), 0):
                severities[code] = severity
    return [
        {
            "code": code,
            "label": FLAG_LABELS.get(code, code.replace("_", " ").title()),
            "severity": severities.get(code, "needs_review"),
            "count": count,
            "detail": examples.get(code, ""),
        }
        for code, count in counts.most_common()
    ]


def audit_email_tone(lead: dict, phrase_counts: Counter | None = None, checked_at: str | None = None) -> dict:
    draft_type, variants = _extract_variants(lead)
    if not variants:
        return {
            "status": "strong",
            "checked_at": checked_at or _now(),
            "flags": [],
            "variant_checks": [],
            "draft_type": "none",
        }

    variant_checks = [
        _audit_variant(lead, variant, i, phrase_counts=phrase_counts)
        for i, variant in enumerate(variants)
    ]

    if draft_type == "single":
        _add_flag(
            variant_checks[0]["flags"],
            "old_single_draft",
            "needs_review",
            "Older one-email draft. Review against the v4 three-variant style.",
        )
        variant_checks[0]["status"] = _status_from_flags(variant_checks[0]["flags"])

    ai_indexes = [
        i for i, variant in enumerate(variants)
        if _mentions_ai(variant.get("body") or "")
    ]
    if len(ai_indexes) > 1:
        for i in ai_indexes:
            _add_flag(variant_checks[i]["flags"], "ai_overused", "needs_review", "AI appears in multiple variants for this lead.")
            variant_checks[i]["status"] = _status_from_flags(variant_checks[i]["flags"])

    for i, variant in enumerate(variants):
        if _lead_needs_taste_first_ai(variant.get("body") or "", lead):
            _add_flag(variant_checks[i]["flags"], "ai_needs_fit", "needs_review", "For premium service niches, lead with taste and trust before AI.")
            variant_checks[i]["status"] = _status_from_flags(variant_checks[i]["flags"])

    flags = _aggregate_flags(variant_checks)
    return {
        "status": _status_from_flags(flags),
        "checked_at": checked_at or _now(),
        "flags": flags,
        "variant_checks": variant_checks,
        "draft_type": draft_type,
    }


def phrase_counts_for_leads(leads: list[dict]) -> Counter:
    counts: Counter = Counter()
    for lead in leads:
        _, variants = _extract_variants(lead)
        for variant in variants:
            lower = (variant.get("body") or "").lower()
            for phrase in OVERUSED_PHRASES:
                if phrase in lower:
                    counts[phrase] += 1
    return counts


def _skeleton_shingles(body: str, lead: dict) -> set:
    """5-word shingles of the body with lead-specific tokens (company, city,
    domain) stripped, so clones with swapped merge slots still match."""
    drop = set()
    for source in (lead.get("name", ""), lead.get("city", ""),
                   _domain_from_url(lead.get("website", "")) or ""):
        for tok in re.findall(r"[a-z0-9']+", str(source).lower()):
            if len(tok) >= 3:
                drop.add(tok)
    words = [w for w in re.findall(r"[a-z']+", (body or "").lower()) if w not in drop]
    return {" ".join(words[i:i + 5]) for i in range(len(words) - 4)}


def find_clone_bodies(leads: list[dict]) -> dict[str, str]:
    """Map lead_id -> another company whose variant A body is near-identical
    (>= 60% shared 5-word shingles). Catches mail-merge clones that
    per-phrase checks miss."""
    entries = []
    for lead in leads:
        _, variants = _extract_variants(lead)
        if not variants:
            continue
        shingles = _skeleton_shingles(variants[0].get("body") or "", lead)
        if len(shingles) >= 10:
            entries.append((lead.get("id", ""), lead.get("name", ""), shingles))

    index: dict[str, list[int]] = {}
    for i, (_id, _name, shingles) in enumerate(entries):
        for s in shingles:
            index.setdefault(s, []).append(i)

    pair_counts: Counter = Counter()
    for owners in index.values():
        if len(owners) > 20:
            continue  # too common to be discriminative
        for a in range(len(owners)):
            for b in range(a + 1, len(owners)):
                pair_counts[(owners[a], owners[b])] += 1

    clones: dict[str, str] = {}
    for (a, b), shared in pair_counts.items():
        min_len = min(len(entries[a][2]), len(entries[b][2]))
        if min_len and shared / min_len >= 0.6:
            clones.setdefault(entries[a][0], entries[b][1])
            clones.setdefault(entries[b][0], entries[a][1])
    return clones


def audit_many_email_tones(leads: list[dict]) -> dict:
    checked_at = _now()
    phrase_counts = phrase_counts_for_leads(leads)
    clone_partners = find_clone_bodies(leads)
    audits_by_id = {}
    counts = {"strong": 0, "needs_review": 0, "risky": 0}
    common_flags: Counter = Counter()
    rows = []

    for lead in leads:
        draft_type, variants = _extract_variants(lead)
        if not variants:
            continue
        audit = audit_email_tone(lead, phrase_counts=phrase_counts, checked_at=checked_at)
        lead_id = lead.get("id", "")
        clone_partner = clone_partners.get(lead_id)
        if clone_partner:
            audit["flags"].append(_flag(
                "clone_body", "needs_review",
                f"Variant A body is nearly identical to {clone_partner}'s draft. Personalise before sending."))
            audit["flags"][-1]["count"] = 1
            audit["status"] = _status_from_flags(audit["flags"])
        audits_by_id[lead_id] = audit
        status = audit.get("status", "strong")
        counts[status] = counts.get(status, 0) + 1
        for flag in audit.get("flags", []):
            common_flags[flag["code"]] += flag.get("count", 1)
        rows.append({
            "id": lead_id,
            "name": lead.get("name", ""),
            "status": lead.get("status", ""),
            "priority": lead.get("priority", ""),
            "tone_status": status,
            "draft_type": draft_type,
            "flags": audit.get("flags", []),
        })

    return {
        "counts": counts,
        "total_with_drafts": len(audits_by_id),
        "common_flags": [
            {
                "code": code,
                "label": FLAG_LABELS.get(code, code.replace("_", " ").title()),
                "count": count,
            }
            for code, count in common_flags.most_common()
        ],
        "leads": rows,
        "audits_by_id": audits_by_id,
        "note": "Local email tone audit, no API usage",
    }
