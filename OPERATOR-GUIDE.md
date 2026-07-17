# OutreachIQ Operator Guide

This guide is for the AI assistant (Claude Code, Codex, or similar) working alongside the operator of this OutreachIQ installation. The dashboard exports JSON files, you process them following the specs below, and the operator imports your output back into the dashboard.

Before writing any emails, read `./memory.md` (the operator's profile, tone notes, and learnings). If it does not exist, ask the operator to copy `memory.example.md` to `memory.md` and fill it in.

## Running the Server

```bash
pip install -r requirements.txt
python server.py
```

Dashboard opens at **http://localhost:5001**

## System Overview

```
data/prospects.json     Main database (all leads)
data/to_score.json      Exported unscored leads (assistant reads this)
data/scored.json        Scored results (assistant writes this)
data/to_write.json      Leads exported for email writing (assistant reads this)
data/written.json       Email drafts (assistant writes this, dashboard imports)
data/exports/           CSV exports
emails/                 Archived sent emails (one .md file per email)
memory.md               Outreach brain (operator profile, tone, structure)
email-log.md            Pipeline tracker table
```

## Status Lifecycle

`unscored` > `hot` / `warm` / `cold` / `skip` > `drafted` > `sent` > `follow-up` > `replied` > `meeting` > `converted`

A `sent` lead whose email bounces becomes `bounced` (detected automatically from Gmail). "Requeue bounced" in the dashboard returns it to `drafted` for re-approval and resend. A `sent` lead that gets a threaded bump becomes `follow-up`. Replies and bounces are pulled from Gmail automatically while the server runs (every `REPLY_POLL_MINUTES`, default 360) and also via the "Check replies" button; both update `email-log.md` on their own.

---

## Your Profile (fill this in)

Scoring and email writing need context about who is doing the outreach. Fill in this block (and mirror it in `memory.md`):

- **Who you are**: name, role, location
- **What you sell**: your services, ordered by priority (the shipped presets use branding, web design, editorial and print, and AI systems as an example catalog; replace with your own)
- **Positioning**: who your ideal client is (size, industry, market) and what makes you the right fit
- **Proof points you can honestly claim**: past clients, projects, or results you have permission to mention
- **Exclusions**: services or industries you do not want to pitch

Everything below refers back to this profile. Where the specs say "your primary offer" or "a similar project you worked on", use the profile, never invented claims.

---

## Section 1: Score Leads

When the operator says **"score my prospects"** or **"score leads"**:

1. Read `data/to_score.json` (array of unscored leads)
2. Evaluate each lead using the scoring criteria below
3. Write results to `data/scored.json`
4. Do NOT write email drafts during scoring
5. Tell the operator how many leads were scored and the breakdown (hot / warm / cold / skip)
6. Remind them to click "Import Scores" in the dashboard

### Scoring Criteria

Each lead in `to_score.json` includes prospecting context and enrichment fields from Firecrawl and Apollo: `service_focus`, `service_mix`, `primary_service`, `secondary_services`, `outreach_angle`, `search_mode`, `partner_lane`, `search_query`, `website_summary`, `brand_signals`, `company_size`, `industry_apollo`, `founded_year`, `estimated_revenue`, `apollo_keywords`. Use these fields to inform the score. Prefer real data over guessing from the name alone.

| Range | Priority | Meaning |
|-------|----------|---------|
| 80-100 | hot | No website, brand-new business, or high-value industry with a clear need for the operator's services |
| 60-79 | warm | Has a basic website but weak or generic branding. Established but looks unprofessional |
| 40-59 | cold | Established, probably has decent branding. Low priority |
| 0-39 | (skip) | Franchise, large corporate, government, or competitor. Not a fit |

### Signals that INCREASE the score

- No website (needs everything from scratch)
- Very few reviews (<5) = brand new business
- High-value industry: real estate, architecture, hospitality, luxury, finance, law
- Location in a wealthy market (Dubai, London, Singapore, USA, Nordics)
- Website exists but looks outdated or amateur (use `website_summary` and `brand_signals`)
- `company_size` 1-50 employees with no Apollo LinkedIn = likely needs brand work
- `founded_year` within the last 2 years = hot (brand new, needs everything)
- `brand_signals` shows sparse content or no headings = weak online presence

### Signals that DECREASE the score

- Industry or service type the operator has excluded in their profile
- Government or public institution
- Franchise or chain (branding decided at corporate level)
- 500+ reviews (very established, unlikely to rebrand)
- Already has strong professional branding (luxury keywords + social proof in `brand_signals`)
- `company_size` 500+ employees = large corporate, skip
- `estimated_revenue` $100M+ = enterprise, not the target unless specifically relevant

### Agency Partner Scoring

If `search_mode` is `agency_partner` or `partner_lane` is true, score the lead as an overflow/collaboration partner, not as a company that needs the operator's services directly.

- Increase score for boutique agencies with strong clients, small teams, broad service menus, or an obvious gap the operator's specialty fills
- Decrease score for large agencies, agencies focused only on services outside the operator's lane, or direct competitors with a strong in-house team covering the same specialty
- `score_reason` should explain partner fit, capacity fit, or service-gap fit
- `brand_gap` should describe the collaboration opportunity, not criticize the agency's own brand

### scored.json Output Format

Write `data/scored.json` with this exact structure:

```json
[
  {
    "id": "ChIJ...",
    "score": 85,
    "priority": "hot",
    "score_reason": "New real estate agency in Dubai with no website. Perfect candidate for a full brand identity.",
    "brand_gap": "No online presence. Needs logo, website, business cards, property brochure templates.",
    "outreach_subject": "Your brand identity - quick idea for [Company]",
    "linkedin_note": "Hi! I came across [Company] and was impressed by what you're building in [City]. I work with [industry] firms on [your specialty]. Would love to connect. - {Your Name}"
  }
]
```

### Scoring Rules

- `score_reason`: 1-2 sentences maximum
- `brand_gap`: 1-2 sentences identifying what they are missing
- `outreach_subject`: short, specific email subject line mentioning their company name. Avoid generic subjects
- `linkedin_note`: LinkedIn connection note, MAX 300 characters. Short, warm, personal. Mention their company, what impressed you, and what the operator does. End with "- {Your Name}" (plain ASCII, no accented characters, to avoid encoding issues)
- `id` must match exactly (it is the Google Places ID used for merging)
- For leads scoring below 40: set `priority` to `""` and leave `outreach_subject` and `linkedin_note` as `""`

---

## Section 2: Write Email Variants (Three Angles)

When the operator says **"write emails"** or **"write email for [company]"**:

1. ALWAYS read `./memory.md` first (operator profile, tone, variant structure, learnings)
2. Read `data/to_write.json` (array of leads that need emails written)
   - If a lead has `repair_mode: true`, treat it as a focused repair, not a full rewrite.
   - Use `existing_variants` and `repair_variant_index`.
   - Replace only the requested variant unless another variant must change for consistency.
   - Preserve unchanged variants exactly.
   - If there are no `existing_variants`, convert the old single draft into exactly 3 variants.
   - Follow `repair_action` and `repair_instruction`.
   - Write the normal `data/written.json` schema with the full `variants` array so the dashboard can import it.
3. For each lead in the array:
   a. Read prospecting and enrichment fields first: `service_focus`, `service_mix`, `primary_service`, `secondary_services`, `service_guidance`, `search_mode`, `partner_lane`, `outreach_angle`, `website_summary`, `brand_signals`, `contact_page_email`, `apollo_linkedin_url`, `company_size`, `founded_year`, `estimated_revenue`. These replace the initial website visit.
   b. Run a web search: "[company name] [city] founder owner CEO CMO director LinkedIn" to find named decision-makers and their personal LinkedIn profiles. Also look for recent posts/activity for engagement suggestions.
   c. Look at their website if `website_summary` is missing or you need more specific detail.
   d. If `contact_page_email` is populated in the lead, pre-fill `contact_email` with it. Override only if a better direct email is found during research.
   e. Identify the **trigger** (why this lead, why now): no website, new business, hiring, funding, weak branding, new market entry, agency overflow potential, etc.
   f. Write 3 email variants (Observation, Peer, Opportunity). Each under 80 words. Each with a different interest-based CTA.
   g. Edit each variant in seven passes: Clarity, Voice, Specificity, Conciseness, Structure, Rhythm, Proofreading.
   h. Draft LinkedIn connection notes and follow-up messages per decision-maker (max 300 chars each). Generate engagement suggestions (1-2 specific posts to like/comment on).
4. Write all results to `data/written.json` (see output schema below)
5. Remind the operator to click "Import Emails" in the dashboard

### Core Philosophy

- **The operator's voice:** warm, observant, premium, direct. The email should feel like a specialist noticed something specific, not like a sales sequence.
- **Elevate, don't diagnose.** Never say "your brand is weak." Say "what you're building deserves a brand that matches."
- **Value is in the email itself.** The observation, the taste, the thinking. Not behind a paywall.
- **One unified offer.** Do not split the pitch into separate service pitches.
- **Under 80 words.** Every variant. No exceptions.
- **Concrete evidence required.** Every email must use one real detail from enrichment, the website, reviews, LinkedIn, Google, or a saved snapshot.
- For `agency_partner` leads, write as a specialist collaborator for overflow work. Do not diagnose their own brand.

### Smart Service Mix Rules

- Default `service_mix` is `smart_mix`. Use `primary_service` as the main offer and `secondary_services` only as supporting context.
- Each email body should mention one clear primary offer and at most one supporting service.
- Do not list all services like a menu. Even when `service_mix` is `all_services`, keep the first email focused.
- A secondary specialty (such as AI systems in the example catalog) should appear only when `primary_service` or `secondary_services` names it, or `outreach_angle` clearly points to it.
- Services the operator has excluded in their profile never appear in any mix.

### Tone QA Rules

- Use a real first name only when confident. If no person is confirmed, use "Hi team,".
- Never greet with company fragments like "Hi The,", "Hi Hotel,", "Hi Interior,", "Hi Athletic,", or "Hi Luxury,".
- Avoid repeated template phrases across a batch: "I came across", "deserves a brand", "AI tools", "the proof you already have".
- Mention a secondary specialty only when it strengthens the offer. For luxury, real estate, architecture, hospitality, and interior design, lead with taste, trust, positioning, and client perception.
- The email must not feel like a diagnosis. It should make the prospect feel seen, capable, and worth a stronger presence.
- If the draft triggers tone audit warnings in the dashboard, edit it before sending.

### Variant A: "The Observation"

- Lead with a specific, genuine observation about their company (something positive)
- Bridge to how the operator's primary offer could amplify what they already have, with one supporting service only when the mix clearly fits
- Interest CTA
- Tone: curious, warm, specific

### Variant B: "The Peer"

- Reference a similar company/project the operator worked on (natural, not forced, and only proof points from the profile)
- Draw a parallel between what that company achieved and what this prospect could achieve
- Interest CTA
- Tone: collegial, one professional to another

### Variant C: "The Opportunity"

- Lead with a market/industry insight positioning their company as having untapped potential
- Show how the right primary offer unlocks that potential, supported by a secondary service only when the service mix calls for it
- Interest CTA
- Tone: forward-looking, ambitious, elevating

### CTA Options (rotate, never repeat the same one for one lead)

- "Is this something you've been thinking about?"
- "Worth a conversation?"
- "Is this on your radar?"
- "Would that be useful?"

### Subject Line Strategy

Each variant gets a different subject line. 21-40 characters optimal:

- Variant A: "Your next move, [Company]" / "Quick thought on [Company]"
- Variant B: "[Similar company] reminded me of you"
- Variant C: "[Industry] brands in [City]" / "[Company]'s edge"

### What NEVER goes in any email

- "I put together a few ideas. Want me to send them over?" (creates work)
- Credentials dump (years of experience, client counts, country counts)
- Portfolio links in the body
- "If it's useful" / "if it resonates" (hedge phrases)
- Em dashes
- Meeting requests ("15-minute call")
- Criticism of their current brand (even indirect)

### written.json Output Schema

Write `data/written.json` as an array. One entry per lead:

```json
[
  {
    "id": "ChIJ...",
    "contact_email": "founder@company.com",
    "trigger": "New luxury property firm in Oslo, zero online presence",
    "ai_addon": "",
    "outreach_subject": "Subject from Variant A (backward compat)",
    "outreach_draft": "Body from Variant A (backward compat)",
    "variants": [
      {
        "label": "A",
        "approach": "observation",
        "subject": "Your next move, [Company]",
        "body": "Hi [Name],\n\n..."
      },
      {
        "label": "B",
        "approach": "peer",
        "subject": "[Similar company] reminded me of you",
        "body": "Hi [Name],\n\n..."
      },
      {
        "label": "C",
        "approach": "opportunity",
        "subject": "Quick thought on [Company]",
        "body": "Hi [Name],\n\n..."
      }
    ],
    "linkedin_profiles": [
      {
        "name": "Sarah Chen",
        "title": "CEO & Co-founder",
        "url": "https://linkedin.com/in/schen",
        "connection_note": "Hi Sarah, I came across [Company] and loved what you're building in [City]. I work with [industry] firms on [your specialty]. Would love to connect. - {Your Name}",
        "follow_up_message": "Hi Sarah, thanks for connecting. I noticed [Company] is growing fast and thought there might be a fit with what I do. I help founders build brands that attract the right clients from the start. Would a quick call make sense? - {Your Name}",
        "engagement_suggestions": [
          "Like her post about [topic] from [date]",
          "Comment on her article about [topic]: '[specific comment]'"
        ]
      }
    ]
  }
]
```

### Rules

- `outreach_draft`: set to Variant A body for backward compatibility. No signature (the dashboard appends it).
- `outreach_subject`: set to Variant A subject for backward compatibility.
- `variants`: array of exactly 3 objects. Each has `label` (A/B/C), `approach` (observation/peer/opportunity), `subject`, `body`.
- Every variant body must be under 80 words.
- `linkedin_profiles`: 1-3 profiles maximum. If only one person found, include just one entry.
- Each `connection_note` must be under 300 characters. End with "- {Your Name}" (plain ASCII, no accented characters). Short, warm, no pitch.
- Each `follow_up_message` is the first message sent after connection accepted. 3-5 sentences. Personal, low-pressure. End with "- {Your Name}".
- `engagement_suggestions`: 1-2 specific actions (like a post, comment on an article). Reference real content found during web search.
- `contact_email`: include if found via web search or on the company website contact page. Empty string if not found.
- `trigger`: 1 sentence explaining why this lead is being contacted now.
- `ai_addon`: optional. Leave `""` unless a secondary-offer add-on clearly fits. If included, follow the AI Add-On rules in Section 2.5. It never replaces a variant and never appears inside the 3 main bodies.
- `id` must match exactly (used for merging back into prospects.json).
- No em dashes in any email body, subject line, or LinkedIn note.

---

## Section 2.5: Write AI Add-Ons (optional P.S.)

When the operator says **"write AI add-ons"** or clicks **Export AI Add-ons** in the dashboard:

1. Read `data/to_ai_addon.json` (hot/warm leads not yet sent, each with `name`, `niche`, `city`, `company_size`, `audience` = team or individual, `decision_maker`, `trigger`).
2. Write one short `ai_addon` per lead to `data/ai_addon.json` as an array of `{ "id", "ai_addon" }`.
3. Remind the operator to click **Import AI Add-ons** in the dashboard.

### What the AI add-on is

A single short P.S. that signals the operator does not only offer the primary service: they can also help a team or an individual put AI to work, or teach them. It rides along with the main email (appended after the body, before the signature) only when the operator toggles it on per lead. The 3 main variants stay led by the primary offer and free of the add-on topic. This is NOT a separate pitch and NEVER replaces a variant. Only write add-ons if the operator's profile actually includes this secondary offer.

### Rules

- One sentence or two, under ~40 words. No em dashes. No meeting ask. No links.
- Open it as a clear "by the way" (a P.S.), so the primary offer stays the lead.
- Frame by `audience`: `team` leans "help your team / train them"; `individual` leans "help you / teach you the ropes".
- Use a credibility hook lightly, drawn from the operator's real profile.
- Keep it specific to the lead where natural (mention the company), but never diagnose.

### ai_addon.json output format

```json
[
  { "id": "ChIJ...", "ai_addon": "P.S. Branding is my main work, but I also help teams get real value from AI day to day, hands-on or as training. Happy to share what would fit [Company]." }
]
```

Examples:
- Team: "P.S. Branding is my main work, but I also help teams get real value from AI day to day, hands-on or as training. Glad to share what would fit [Company]."
- Individual: "P.S. Beyond the brand side, I also help people use AI well day to day, with me or by teaching the ropes. Happy to point you to what fits."

---

## Section 2.6: Write Follow-Ups (threaded bumps)

When the operator says **"write follow-ups"** or clicks **Export follow-ups** in the dashboard:

1. Read `data/to_followup.json` (sent leads past `FOLLOW_UP_DAYS` with no reply; each includes `sent_subject`, `sent_body`, `days_since`, `follow_up_count`, `trigger`, `website_summary`, `brand_signals`, `search_mode`, `decision_maker`).
2. Write one short bump per lead to `data/followup_written.json` as an array of `{ "id", "body" }`.
3. Remind the operator to click **Import follow-ups**, then **Send follow-ups**. Sends go as Gmail replies inside the original thread with subject "Re: [original subject]", signature appended automatically.

### Follow-up rules

- Under 60 words. Two or three sentences. The send gate blocks longer.
- Reference the specific observation from `sent_body` in fresh words; never repeat it verbatim.
- Add exactly ONE new element: a fresh detail about their company, a small concrete idea, or a relevant thought since the first email. A bump with nothing new burns the lead.
- Banned (send gate blocks these): "just following up", "bumping this", "circling back", "checking in", "floating this", any meeting ask, em dashes.
- Retired phrases from the tone rules apply here too ("I came across", "caught my eye", "stood out through").
- Same greeting as the original email (same person, or "Hi team,"). No signature, no links, no credentials.
- End with an interest question DIFFERENT from the original email's CTA.
- For `agency_partner` leads, stay in the collaborator frame.

Example shape:

```
Hi Dhanya,

One more thought on the word-of-mouth point: boutiques with your review depth usually see search traffic they never capture. A simple one-page site would catch it.

Still relevant this quarter?
```

---

## Section 3: Log and Track

When the operator says **"log it"**, **"mark as sent"**, or **"update [company] to [status]"**:

1. Update the status in `email-log.md` for that company
2. Update the prospect's `status` field in `data/prospects.json` to the new status
3. If marking as sent, also set `date_sent` to today's date

Valid statuses: `unscored`, `hot`, `warm`, `cold`, `skip`, `drafted`, `sent`, `replied`, `meeting`, `converted`

---

## Section 4: Update Memory

When the operator says **"update memory"** or **"add this to memory"**:

1. Read `./memory.md`
2. Add the new learning to the appropriate section (What Works, What to Avoid, or Learnings Log)
3. Keep it concise. One or two lines per learning.
4. Do not change the structure or other sections

---

## Data Files Reference

| File | Purpose |
|------|---------|
| `data/prospects.json` | Main database (flat list of all leads) |
| `data/to_score.json` | Slim export for scoring (assistant reads), includes enrichment fields |
| `data/scored.json` | Scored results (assistant writes, dashboard imports) |
| `data/to_write.json` | Leads exported for email writing (assistant reads), includes enrichment fields |
| `data/written.json` | Email drafts (assistant writes, dashboard imports) |
| `data/to_ai_addon.json` | Hot/warm unsent leads exported for AI add-on writing (assistant reads) |
| `data/ai_addon.json` | AI add-on P.S. lines (assistant writes, dashboard imports) |
| `data/to_followup.json` | Sent leads due a bump, with original email context (assistant reads) |
| `data/followup_written.json` | Follow-up bumps (assistant writes, dashboard imports then archives) |
| `data/exports/` | CSV exports for archiving |
| `emails/` | One .md file per email, named YYYY-MM-DD_company-name.md |
| `memory.md` | Outreach brain: profile, tone, structure, learnings |
| `email-log.md` | Pipeline tracker table |

### Enrichment fields (added automatically after Google Places search)

| Field | Source | Notes |
|-------|--------|-------|
| `enriched_at` | pipeline | ISO timestamp when enrichment last ran |
| `website_summary` | Firecrawl | First ~500 chars of page markdown |
| `brand_signals` | Firecrawl | One-line heuristic: luxury keywords, headings, mailto, form-heavy |
| `contact_page_email` | Firecrawl | First real email found on the page |
| `company_size` | Apollo | Estimated employee count |
| `industry_apollo` | Apollo | Industry label from Apollo |
| `founded_year` | Apollo | Year founded |
| `estimated_revenue` | Apollo | Revenue band (e.g. "$1M-$10M") |
| `apollo_keywords` | Apollo | Up to 10 topic keywords |
| `apollo_linkedin_url` | Apollo | Company LinkedIn page URL |

## Writing Rules (apply to everything)

- No em dashes in any output. Use commas, colons, full stops, or brackets instead.
- All UI text and documentation in English
- Short and direct. No filler words.
