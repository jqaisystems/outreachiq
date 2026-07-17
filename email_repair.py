"""Deterministic local repairs for OutreachIQ email drafts.

This module does not call any AI or paid provider. It prepares cleaner v4
variants for drafts that already exist in the local JSON database.
"""

from __future__ import annotations

import re

from email_tone import _SELF_DOMAIN, audit_email_tone, word_count


CONTACT_FIELDS = ("contact_email", "contact_page_email")
SOFT_CTAS = [
    "Is this something you've been thinking about?",
    "Worth a conversation?",
    "Is this on your radar?",
]


def _first_name(value: str) -> str:
    match = re.search(r"[A-Za-z][A-Za-z']+", value or "")
    if not match:
        return ""
    name = match.group(0)
    if name.lower() in {
        "the",
        "hotel",
        "interior",
        "athletic",
        "luxury",
        "design",
        "real",
        "estate",
        "studio",
        "space",
        "company",
        "group",
        "properties",
        "services",
        "homes",
        "team",
        "owner",
        "founder",
        "ceo",
        "director",
        "managing",
        "manager",
        "president",
        "realtor",
    }:
        return ""
    return name


def greeting_for(lead: dict) -> str:
    name = _first_name(lead.get("decision_maker", ""))
    if name:
        return f"Hi {name},"
    for profile in lead.get("linkedin_profiles") or []:
        name = _first_name(profile.get("name", ""))
        if name:
            return f"Hi {name},"
    return "Hi team,"


def contact_email_for(lead: dict) -> str:
    for field in CONTACT_FIELDS:
        value = (lead.get(field) or "").strip()
        if value:
            return value
    for value in lead.get("contact_page_emails") or []:
        if value:
            return str(value).strip()
    for candidate in lead.get("contact_candidates") or []:
        value = candidate.get("email") or candidate.get("value")
        if value:
            return str(value).strip()
    return ""


def category_for(lead: dict) -> str:
    text = " ".join([
        str(lead.get("industry") or ""),
        str(lead.get("niche") or ""),
        str(lead.get("industry_apollo") or ""),
        str(lead.get("apollo_keywords") or ""),
        str(lead.get("name") or ""),
    ]).lower()
    if "hotel" in text or "hospitality" in text or "restaurant" in text:
        return "hospitality"
    if "real estate" in text or "realtor" in text or "property" in text or "homes" in text:
        return "real estate"
    if "architect" in text:
        return "architecture"
    if "interior" in text:
        return "interior design"
    if "fitness" in text or "gym" in text or "club" in text:
        return "fitness"
    if "construction" in text or "contractor" in text:
        return "construction"
    if "law" in text or "legal" in text:
        return "legal services"
    if "finance" in text or "wealth" in text or "investment" in text:
        return "financial services"
    return "service"


def intro_for(lead: dict) -> str:
    text = " ".join([
        str(lead.get("industry") or ""),
        str(lead.get("niche") or ""),
        str(lead.get("industry_apollo") or ""),
        str(lead.get("apollo_keywords") or ""),
        str(lead.get("name") or ""),
        str(lead.get("search_mode") or ""),
        str(lead.get("score_reason") or ""),
    ]).lower()
    if lead.get("partner_lane") or lead.get("search_mode") == "agency_partner":
        return "I'm Jo\u00e3o, a senior brand identity specialist available for overflow identity work."
    if "architect" in text or "interior" in text:
        return "I'm Jo\u00e3o, a brand identity designer for design-led and built-environment firms."
    if "real estate" in text or "property" in text or "homes" in text or "luxury" in text:
        return "I'm Jo\u00e3o, a brand identity designer working with property and luxury firms."
    if "finance" in text or "wealth" in text or "investment" in text or "accounting" in text or "advisory" in text:
        return "I'm Jo\u00e3o, a brand identity designer helping specialist firms sharpen perception."
    return "I'm Jo\u00e3o, a brand identity designer helping specialist firms sharpen perception."


def _context_text(lead: dict) -> str:
    return " ".join([
        str(lead.get("industry") or ""),
        str(lead.get("niche") or ""),
        str(lead.get("industry_apollo") or ""),
        str(lead.get("apollo_keywords") or ""),
        str(lead.get("name") or ""),
        str(lead.get("search_query") or ""),
        str(lead.get("website_summary") or ""),
        str(lead.get("brand_signals") or ""),
        str(lead.get("score_reason") or ""),
        str(lead.get("brand_gap") or ""),
    ])


def proof_for(lead: dict) -> str:
    raw_review_count = lead.get("review_count")
    if raw_review_count is not None and str(raw_review_count).strip() != "":
        review_count = int(raw_review_count or 0)
        if review_count <= 5:
            return f"With {review_count} reviews, the public footprint is still early."
        if review_count >= 100:
            return f"With {review_count} reviews, there is already real trust behind it."
        return f"The {review_count} reviews support that story."
    founded_year = lead.get("founded_year")
    if founded_year:
        return f"Founded in {founded_year}, the company has a concrete story to build from."
    company_size = lead.get("company_size")
    if company_size:
        return f"With around {company_size} people, the team has enough scale to make the brand work harder."
    domain = lead.get("website")
    if domain and domain != "NONE":
        return f"The website at {domain.replace('https://', '').replace('http://', '').split('/')[0]} gives prospects a place to judge that first."
    return "The first impression is still open enough to shape clearly."


def hook_for(lead: dict) -> str:
    existing = _hook_from_existing_variants(lead)
    if existing:
        return existing

    text = _context_text(lead).lower()
    category = category_for(lead)
    if lead.get("partner_lane") or lead.get("search_mode") == "agency_partner":
        return "your service mix points to a natural collaboration fit for overflow brand identity work"
    if category in {"architecture", "interior design"}:
        terms = [
            label for token, label in [
                ("architecture", "architecture"),
                ("interior", "interiors"),
                ("scenograph", "scenography"),
                ("furniture", "furniture"),
                ("object", "objects"),
                ("residential", "residential work"),
            ]
            if token in text
        ]
        if len(terms) >= 2:
            return f"your work crosses {', '.join(dict.fromkeys(terms[:5]))}"
        return "the studio's work depends on taste, detail, and client trust being clear quickly"
    if category == "financial services":
        keywords = [
            label for token, label in [
                ("tax", "tax planning"),
                ("wealth", "wealth advice"),
                ("retirement", "retirement planning"),
                ("estate", "estate planning"),
                ("cfo", "fractional finance leadership"),
                ("accounting", "accounting and advisory"),
                ("investment", "investment advice"),
            ]
            if token in text
        ]
        if keywords:
            return f"your focus on {keywords[0]} gives the firm a specific trust story"
        return "specialist advice firms need trust and clarity before prospects compare options"
    if category == "real estate":
        return "property clients judge taste, trust, and confidence before they make contact"
    if category == "construction":
        return "custom building work needs practical credibility and premium trust to show up quickly"
    if category == "fitness":
        return "fitness clients judge energy, trust, and professionalism before they ever visit"
    if category == "hospitality":
        return "guest perception starts before the booking, visit, or first enquiry"
    return "the offer has enough specificity to deserve a clearer first impression"


def _hook_from_existing_variants(lead: dict) -> str:
    variants = lead.get("email_variants") or lead.get("existing_variants") or []
    for variant in variants:
        body = variant.get("body") or ""
        for sentence in _body_sentences(body):
            hook = _naturalize_hook_sentence(lead, sentence)
            if hook:
                return hook
    return ""


def _body_sentences(body: str) -> list[str]:
    text = re.sub(r"^Hi\s+[^,\n]+,\s*", "", body or "", flags=re.IGNORECASE).strip()
    text = re.split(r"\n\s*\n", text, maxsplit=1)[0]
    protected = {
        "& Co.": "& Co<prd>",
        "Inc.": "Inc<prd>",
        "LLC.": "LLC<prd>",
        "GmbH.": "GmbH<prd>",
        "AG.": "AG<prd>",
        "Ltd.": "Ltd<prd>",
    }
    for src, dst in protected.items():
        text = text.replace(src, dst)
    sentences = re.split(r"(?<=[.!?])\s+", text)
    restored = []
    for sentence in sentences:
        for src, dst in protected.items():
            sentence = sentence.replace(dst, src)
        sentence = sentence.strip()
        if sentence:
            restored.append(sentence)
    return restored


def _naturalize_hook_sentence(lead: dict, sentence: str) -> str:
    extracted = re.search(
        r"(?:caught my eye because|stands out because|is that)\s+(.+)$",
        sentence,
        flags=re.IGNORECASE,
    )
    if extracted:
        sentence = extracted.group(1).strip()
    lowered = sentence.lower()
    if (
        "i'm jo" in lowered
        or "i am jo" in lowered
        or "brand identity designer" in lowered
        or "brand identity specialist" in lowered
        or lowered.startswith("my work with")
        or lowered.startswith("work with")
        or lowered.startswith("a lesson from")
        or lowered.startswith("i often see")
        or lowered.startswith("i have helped")
        or lowered.startswith("i came across")
        or lowered.startswith("i help ")
        or lowered.startswith("in ")
        or "useful trust signal" in lowered
        or "the proof you already have" in lowered
        or "deserves a brand" in lowered
    ):
        return ""

    name = short_name(lead.get("name") or "")
    escaped = re.escape(name)
    cleaned = sentence.rstrip(".")
    cleaned = re.sub(r"^I came across\s+.+?\s+and noticed\s+", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"^I noticed\s+", "", cleaned, flags=re.IGNORECASE)

    mix = re.search(r"\bmix of\s+(.+?)\s+give", cleaned, flags=re.IGNORECASE)
    if mix:
        return f"your work crosses {mix.group(1).strip()}, which is rare for a small studio"

    if name:
        cleaned = re.sub(rf"^{escaped}'s\s+\d+\s+Google\s+reviews?\s+and\s+", "your ", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(rf"^{escaped}'s\s+\d+\s+reviews?\s+and\s+", "your ", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(rf"^{escaped}\s+already\s+has\s+\d+\s+reviews?\s+and\s+", "your ", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(rf"^{escaped}\s+has\s+a\s+", "the ", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(rf"^{escaped}'s\s+", "your ", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(rf"^{escaped}\s+", "the company ", cleaned, flags=re.IGNORECASE)

    cleaned = re.sub(r"\b\d+\s+Google\s+reviews?\s+and\s+", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\b\d+\s+reviews?\s+and\s+", "", cleaned, flags=re.IGNORECASE)
    cleaned = cleaned.replace(" feel ", " feels ")
    cleaned = cleaned.replace(" create ", " creates ")
    cleaned = cleaned.strip(" ,")
    if not cleaned:
        return ""
    return cleaned[0].lower() + cleaned[1:]


def opportunity_for(lead: dict) -> str:
    category = category_for(lead)
    if lead.get("partner_lane") or lead.get("search_mode") == "agency_partner":
        return "A clearer specialist position could make you easier to bring in when clients need senior identity work."
    if category in {"architecture", "interior design"}:
        return "A sharper identity could give that range one clear thread, so clients understand the studio faster."
    if category == "financial services":
        return "A sharper identity could make that expertise easier to trust before prospects compare firms."
    if category == "real estate":
        return "A sharper identity could make the premium signal clearer across listings, proposals, and first conversations."
    if category == "construction":
        return "A clearer identity could make that quality feel more premium before a client requests a quote."
    if category == "fitness":
        return "A clearer identity could make that trust and energy easier to feel before someone visits."
    if category == "hospitality":
        return "A sharper identity could make the experience feel more considered before guests arrive."
    return "A clearer identity could make that value easier to understand, trust, and remember."


def evidence_for(lead: dict) -> str:
    city = lead.get("city") or lead.get("country") or "your market"
    raw_review_count = lead.get("review_count")
    if raw_review_count is not None and str(raw_review_count).strip() != "":
        review_count = int(raw_review_count or 0)
        return f"{review_count} reviews in {city}"
    founded_year = lead.get("founded_year")
    if founded_year:
        return f"a company founded in {founded_year}"
    company_size = lead.get("company_size")
    if company_size:
        return f"a team of around {company_size} people"
    brand_signals = lead.get("brand_signals")
    if brand_signals:
        cleaned = re.sub(r"\s+", " ", str(brand_signals)).strip().rstrip(".")
        return cleaned[:56]
    if lead.get("website") and lead.get("website") != "NONE":
        return "a visible online presence"
    return f"a clear presence in {city}"


def short_name(name: str) -> str:
    name = re.sub(r"\s+", " ", name or "").strip()
    name = name.replace("\u2013", "-").replace("\u2014", "-")
    name = re.split(r"\s+[|-]\s+", name, maxsplit=1)[0].strip()
    if len(name) <= 42:
        return name
    clipped = name[:42].rsplit(" ", 1)[0].strip()
    return clipped or name[:42].rstrip()


def _limit_words(text: str, limit: int) -> str:
    words = (text or "").split()
    if len(words) <= limit:
        return text
    return " ".join(words[:limit]).rstrip(" ,.;:")


def _generated_variant(lead: dict, label: str, approach: str, cta: str) -> dict:
    name = lead.get("name") or "your company"
    name_short = short_name(name)
    city = str(lead.get("city") or lead.get("country") or "your market").strip()
    # Never let a non-Latin city string (e.g. Arabic from Google Places) leak
    # into English copy; it reads as a mail-merge failure.
    if re.search(r"[Ѐ-ӿ֐-׿؀-ۿ぀-ヿ一-鿿]", city):
        city = str(lead.get("country") or "").strip() or "your market"
    category = category_for(lead)
    greeting = greeting_for(lead)
    intro = intro_for(lead)
    hook = _limit_words(hook_for(lead), 18)
    proof = proof_for(lead)
    opportunity = opportunity_for(lead)

    # The first sentence is always about the prospect, never about the sender, and
    # retired fingerprint phrases ("caught my eye", "Quick thought on") stay out.
    if approach == "observation":
        subject = f"{name_short}'s next chapter"
        body = (
            f"{greeting}\n\n"
            f"At {name_short}, {hook}. {intro}\n\n"
            f"{proof} {opportunity}\n\n"
            f"{cta}"
        )
    elif approach == "peer":
        subject = "A brand clarity thought"
        body = (
            f"{greeting}\n\n"
            f"What stands out about {name_short} is that {hook}. {intro}\n\n"
            f"{proof} The brand opportunity is to make that feel clear before a prospect compares options.\n\n"
            f"{cta}"
        )
    else:
        subject = f"{category} brands in {city}"
        body = (
            f"{greeting}\n\n"
            f"{name_short} stands out because {hook}. {intro}\n\n"
            f"In {city}, {category} clients compare quickly. {proof} {opportunity}\n\n"
            f"{cta}"
        )

    return {
        "label": label,
        "approach": approach,
        "subject": subject[:60],
        "body": body,
    }


def generated_variants(lead: dict) -> list[dict]:
    return [
        _generated_variant(lead, "A", "observation", SOFT_CTAS[0]),
        _generated_variant(lead, "B", "peer", SOFT_CTAS[1]),
        _generated_variant(lead, "C", "opportunity", SOFT_CTAS[2]),
    ]


def _replace_greeting(body: str, greeting: str) -> str:
    lines = (body or "").splitlines()
    for i, line in enumerate(lines):
        if line.strip():
            if re.match(r"^Hi\b", line.strip(), re.IGNORECASE):
                lines[i] = greeting
            else:
                lines.insert(i, greeting)
                lines.insert(i + 1, "")
            return "\n".join(lines)
    return f"{greeting}\n\n"


def _clean_body(body: str, lead: dict) -> str:
    greeting = greeting_for(lead)
    cleaned = _replace_greeting(body or "", greeting)
    replacements = {
        " with branding supported by practical AI tools": " through a clearer brand system",
        "branding supported by practical AI tools": "a clearer brand system",
        "AI-powered": "practical",
        "AI tools": "brand systems",
        "real estate brands": f"{category_for(lead)} brands",
    }
    for src, dst in replacements.items():
        cleaned = cleaned.replace(src, dst)
    lines = [line for line in cleaned.splitlines() if _SELF_DOMAIN not in line.lower() and "portfolio" not in line.lower()]
    cleaned = "\n".join(lines)
    cleaned = re.sub(r"\b(15[- ]?minute|book a call|schedule a call|quick call)\b.*\?", "Worth a conversation?", cleaned, flags=re.IGNORECASE)
    cleaned = cleaned.replace("\u2014", ",").replace("\u2013", ",")
    return cleaned.strip()


def _has_tiny_intro(body: str) -> bool:
    lower = (body or "").lower()
    return (
        "i'm jo" in lower
        or "i am jo" in lower
        or "brand identity designer" in lower
        or "brand identity specialist" in lower
    )


def _variant_needs_generation(lead: dict, variant: dict, phrase_counts=None) -> bool:
    body = variant.get("body") or ""
    if word_count(body) > 80:
        return True
    audit = audit_email_tone({**lead, "email_variants": [variant]}, phrase_counts=phrase_counts)
    if audit.get("status") != "strong":
        return True
    codes = {flag.get("code") for check in audit.get("variant_checks", []) for flag in check.get("flags", [])}
    return not _has_tiny_intro(body) or bool(codes & {
        "bad_greeting",
        "company_fragment_greeting",
        "missing_greeting",
        "hard_cta",
        "portfolio_in_body",
        "credential_dump",
        "ai_overused",
        "ai_needs_fit",
        "over_80_words",
    })


def repair_variants(lead: dict, phrase_counts=None) -> list[dict]:
    existing = lead.get("email_variants") or lead.get("existing_variants") or []
    generated = generated_variants(lead)
    if not existing and lead.get("outreach_draft"):
        return generated
    if not existing:
        return []

    repaired = []
    for index, fallback in enumerate(generated):
        if index < len(existing):
            current = dict(existing[index])
            current["body"] = _clean_body(current.get("body") or "", lead)
            current.setdefault("label", fallback["label"])
            current.setdefault("approach", fallback["approach"])
            current.setdefault("subject", fallback["subject"])
            if _variant_needs_generation(lead, current, phrase_counts=phrase_counts):
                current = fallback
        else:
            current = fallback
        repaired.append(current)
    return repaired[:3]


def repair_written_entry(lead: dict, phrase_counts=None) -> dict | None:
    variants = repair_variants(lead, phrase_counts=phrase_counts)
    if not variants:
        return None
    return {
        "id": lead.get("id", ""),
        "contact_email": contact_email_for(lead),
        "trigger": lead.get("trigger", "") or "",
        "outreach_subject": variants[0].get("subject", ""),
        "outreach_draft": variants[0].get("body", ""),
        "variants": variants,
        "linkedin_profiles": lead.get("linkedin_profiles") or [],
    }
