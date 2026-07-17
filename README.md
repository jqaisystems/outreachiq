# OutreachIQ

A self-hosted lead generation and cold outreach QA dashboard. Find businesses, score them, draft short personalised emails, review every word, and send at a deliberately slow pace.

```
Google Places search
      │
Firecrawl + Apollo enrichment
      │
AI scoring (Claude/Codex file handoff)
      │
Three-variant email drafting (A/B/C)
      │
Local tone audit + deterministic repair
      │
Human review queue
      │
Send gate (blockers + warnings)
      │
Throttled Gmail API sending
      │
Follow-ups, reply/bounce detection, outcome tracking
```

Everything runs locally: a single Flask server, flat JSON files as the database, no external SaaS beyond the APIs you choose to plug in.

## Features

- **Lead search** via Google Places with industry presets, service-led search presets, market presets, and custom queries
- **Enrichment**: Firecrawl website summaries and brand signals, Apollo company data (size, founded year, revenue band, keywords, LinkedIn URL), contact email scraping
- **AI scoring** (0-100, hot/warm/cold/skip) through a file handoff to Claude Code or Codex, no API key needed for the AI step
- **Three email variants per lead** (Observation, Peer, Opportunity), each under 80 words, each with a different soft CTA
- **Local tone audit**: flags overused phrases, banned patterns, bad greetings, self-promotion links, hard sells
- **Deterministic repair**: cleans drafts locally without any AI or paid API call
- **Human review queue**: nothing sends without your approval, edit subject, recipient, and body inline
- **Send gate**: pre-send checks with hard blockers and warnings (duplicate contact, do-not-contact, tone failures, missing recipient)
- **Throttled Gmail sending**: daily cap, delay between sends, kill switch, never-send-twice protection
- **Follow-ups** as threaded Gmail replies, with their own quality rules and send gate
- **Reply and bounce detection** pulled automatically from Gmail while the server runs
- **Pipeline tracking**: full status lifecycle from unscored to converted, CSV exports, per-email markdown archive
- **LinkedIn support**: connection notes and first messages per decision-maker, with engagement suggestions

## Requirements

- Python 3.11+
- A Google Places API key (required, for lead search)
- Firecrawl and Apollo API keys (optional, for enrichment)
- Gmail OAuth credentials (optional, only if you want to send from the dashboard)

## Quick start

```bash
git clone <this repo>
cd OutreachIQ
pip install -r requirements.txt
cp .env.example .env    # add your keys
python server.py
```

Open http://localhost:5001. The step-by-step usage walkthrough is in [docs/guide.md](docs/guide.md).

## API keys

| Provider | Used for | Free tier notes |
|---|---|---|
| Google Places | Lead search (required) | $200/month free credit covers thousands of searches. Enable "Places API (New)" at console.cloud.google.com |
| Firecrawl | Website summaries, brand signals, contact page emails (optional) | Free tier available |
| Apollo | Company enrichment: size, founded year, revenue, keywords, LinkedIn (optional) | Optional org enrichment, free tier available |

The dashboard works without the optional keys. Scoring and drafting just have less context to work with.

## Gmail sending setup (optional)

Sending is off until you complete this. Without it you can still use the Copy button or the pre-filled compose links.

1. Create a project at console.cloud.google.com and enable the **Gmail API**
2. APIs & Services > OAuth consent screen > External > Testing mode, add your Gmail address as a test user
3. Credentials > Create OAuth client ID > **Desktop app** > download the JSON as `client_secret.json` in the repo root
4. Run `python authorize_gmail.py`, grant access in the browser that opens

**Scopes are `gmail.send` and `gmail.readonly` only.** There is no modify or delete scope, so the app can never alter or remove anything in your mailbox. It can send, and it can read to detect replies and bounces. Nothing else.

## Safety by default

Cold outreach tools are easy to abuse. This one ships throttled:

- `DAILY_SEND_CAP=30`: hard daily limit, counted server-side
- `SEND_DELAY_SECONDS=20`: enforced gap between sends
- **Kill switch** in the dashboard: pauses all sending instantly, including mid-batch
- **Do-not-contact list**: blocked emails and domains are never sent to
- **Duplicate-contact blocking**: an address already used for another lead is flagged, and a lead is never sent to twice
- **Send gate**: every send passes a checklist of blockers and warnings first, in the UI and again server-side

Raise the caps in `.env` if you must, but the defaults exist for a reason: small volume plus real personalisation is what actually gets replies.

## How the AI handoff works

There is no AI API key in this app. The AI steps run through your own coding assistant:

1. In the dashboard, click **Export for Scoring** or **Export for Email Writing**. This writes `data/to_score.json` or `data/to_write.json`
2. Ask Claude Code (or Codex) to process the file: "score my prospects" or "write emails". The assistant follows [OPERATOR-GUIDE.md](OPERATOR-GUIDE.md), which contains the full scoring rubric, email specs, and output schemas
3. The assistant writes `data/scored.json` or `data/written.json`
4. Back in the dashboard, click **Import Scores** or **Import Emails**

The same loop covers AI add-ons and follow-ups. A no-AI fallback also exists: `tools/generate_written.ps1` produces deterministic template drafts locally.

## Personalize before sending

The repo ships with neutral placeholders. Before your first real send:

1. Set the `SIGNATURE_*` variables in `.env` (name, title, website, email, phone), or override the whole block with `EMAIL_SIGNATURE`
2. Mirror the same values in the signature preview constants in `static/app.js` (search for `EMAIL_SIGNATURE`), so the dashboard preview matches what the server appends
3. Edit the body templates and `{Your Name}` sign-offs in `tools/generate_written.ps1` so fallback drafts sound like you
4. Copy `memory.example.md` to `memory.md` and fill in your profile, tone notes, and proof points. Your AI assistant reads it before writing emails, and the app appends learnings to it over time
5. Fill in the "Your Profile" section of `OPERATOR-GUIDE.md` so scoring and drafting reflect your actual offer

## Compliance disclaimer

You are solely responsible for how you use this tool and for complying with all applicable law in your jurisdiction and your recipients' jurisdictions, including CAN-SPAM, GDPR, PECR, and equivalent regulations. That includes having a lawful basis for contacting people, using accurate sender identity, and honoring opt-outs and do-not-contact requests promptly.

OutreachIQ is designed for small-scale, human-reviewed B2B outreach: every email is individually researched, drafted, reviewed, and approved by a person before it goes out. It is not a bulk mailer and must not be used for spam.

## Credits

Built by João Queirós ([https://www.ai.joaoqueiros.com](https://www.ai.joaoqueiros.com)). Released under the MIT license, see [LICENSE](LICENSE).
