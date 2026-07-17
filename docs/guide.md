# OutreachIQ - How to Use

A step-by-step guide to the full prospecting and outreach pipeline.

---

## Overview

OutreachIQ is a lead generation and cold outreach system. It finds businesses via Google Maps, scores them with AI, writes personalised emails and LinkedIn messages, and tracks everything in a pipeline dashboard.

**Start the dashboard:**
```
python server.py
```
Opens at http://localhost:5001

---

## The Full Pipeline

```
Search  →  Score  →  Write Emails  →  Send  →  Track
```

Each stage is a separate step. You control when to move to the next one.

---

## Stage 1: Find Leads

1. Open the **Search** tab
2. Pick an industry chip (Real Estate, Tech, Hospitality, etc.)
3. Enter a location (e.g. "Dubai, UAE" or "London, UK")
4. Choose how many results (10, 20, 40, 60)
5. Click **Search Google Maps**

Leads appear in the Pipeline tab with status `unscored`.

**Tip:** Use the custom query field to override the default search (e.g. "luxury interior design studio").

---

## Stage 2: Score Leads

Scoring evaluates each lead and assigns Hot / Warm / Cold / Skip based on branding potential.

1. Go to the **Pipeline** tab
2. Click **Export for Scoring** - this writes `data/to_score.json`
3. Open Claude Code and say: `score my prospects`
4. Claude reads the file, scores every lead, writes `data/scored.json`
5. Back in the dashboard, click **Import Scores**

Leads now show a score (0-100) and a priority badge:

| Badge | Score | Meaning |
|-------|-------|---------|
| Hot | 80-100 | No website or brand new. Priority target. |
| Warm | 60-79 | Weak or generic branding. Good fit. |
| Cold | 40-59 | Established. Low priority. |
| Skip | 0-39 | Franchise, corporate, or competitor. |

---

## Stage 3: Write Emails

1. Filter the pipeline to **Hot** and **Warm** leads
2. Click **Export for Email Writing** - writes `data/to_write.json`
3. Open Claude Code and say: `write emails`
4. Claude researches each company, finds decision-makers on LinkedIn, writes a personalised email and two LinkedIn notes per profile
5. Back in the dashboard, click **Import Emails**

Leads now have a full email draft and LinkedIn profile cards.

---

## Stage 4: Send Outreach

Open any lead by clicking it in the pipeline. The detail panel shows:

**Email section:**
- Edit the subject, recipient email, and body directly
- Click **Open in Gmail** or **Open in Hotmail** to open a pre-filled compose window
- Click **Copy Email** to copy with signature (links are active when pasted into Gmail or Outlook)
- Click **Save Changes** to save edits

**LinkedIn section:**
Each profile card has two notes:
- **Before connecting** (max 300 chars): paste this as the connection request note on LinkedIn
- **After connecting**: paste this as your first message once they accept

Click **Copy** on whichever you need, then go to LinkedIn.

**Scraping emails:**
If the lead has a website, a **Scrape** button appears next to the Contact Email field. Click it to automatically scan the homepage and contact page for email addresses.

---

## Stage 5: Track Progress

After sending, update the lead status:

1. Open the lead detail panel
2. Click the status button at the bottom (Mark Sent, Mark Replied, etc.)

**Status lifecycle:**
```
unscored > hot/warm/cold > drafted > sent > replied > meeting > converted
```

Use the filter tabs at the top of the pipeline to view leads by status.

---

## Exports

| Button | What it exports |
|--------|----------------|
| Export CSV | Pipeline data with scores and contact info |
| Export Full Data | Everything: email drafts, LinkedIn notes, follow-ups, all dates |

Files are saved to `data/exports/` and downloaded automatically.

---

## Working with Claude Code

These are the exact phrases Claude recognises:

| Say this | What happens |
|----------|-------------|
| `score my prospects` | Reads `to_score.json`, writes `scored.json` |
| `write emails` | Reads `to_write.json`, researches each company, writes `written.json` |
| `write email for [Company]` | Writes email for one specific company |
| `update [Company] to sent` | Updates status in pipeline and log |
| `mark [Company] as sent` | Same as above |
| `update memory` | Adds a new learning to the outreach memory file |

---

## Tips

- Always **Import Scores** or **Import Emails** after Claude finishes - the dashboard does not auto-refresh
- The signature is appended automatically at send time. Do not add it to the email body.
- LinkedIn connection notes must be under 300 characters. Claude respects this limit.
- The follow-up message (after connecting) has no character limit - use it to open a real conversation.
- If an email needs rewriting, click **Regenerate with Claude Code** in the detail panel, then say `write emails` in Claude Code and import again.
