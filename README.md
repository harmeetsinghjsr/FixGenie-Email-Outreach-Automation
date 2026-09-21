# FixGenie Outreach System

A **free, self-hosted** lead-generation and cold-outreach pipeline for
**FixGenie Consulting Inc** — your own alternative to paid tools like GMass,
Apollo, or MSG91, built to run at close to **$0/month**.

It discovers small businesses by city + industry, enriches them with owner
names and emails, validates everything, de-duplicates into a Google Sheet that
acts as your CRM, and sends a compliant, personalized email sequence — logging
every result back to the sheet.

```
Discover → Enrich → Validate → De-dup + Store (Google Sheet) → Outreach → Track
```

---

## Why this stack (and why it's free)

| Stage | Tool | Cost |
|---|---|---|
| Discovery | **OpenStreetMap Overpass API** (primary) | Free, unlimited, no key |
| Discovery (booster) | Google Places API | Free $200/mo credit |
| Discovery (opt-in) | Playwright directory scraper | Free |
| Enrichment | Self-built website crawler (+ optional Hunter.io) | Free |
| Validation | `email-validator` + MX DNS + `phonenumbers` | Free, offline |
| De-dup | `rapidfuzz` fuzzy matching | Free |
| Storage / CRM | Google Sheets (`gspread`) | Free |
| Sending | Gmail SMTP (~500/day) **or** Brevo (300/day) | Free tiers |
| Scheduling | GitHub Actions **or** cron **or** n8n | Free |

The one deliberate design choice worth calling out: **Overpass is the primary
source, not Google Places.** It's genuinely free forever with no card on file,
and it returns exactly the fields you need for local businesses. Google Places
is wired in as an optional booster for when you want extra coverage.

---

## Three ways to run it

This repo gives you **all three** paths from the requirements doc, sharing one
Google Sheet schema so you can mix and match:

1. **Python pipeline** (main engine) — full control, best dedup/validation.
2. **n8n workflows** (`/n8n`) — no-code, importable JSON, great for scheduling
   and the auto-email-on-new-row trigger.
3. **Google Apps Script** (in `docs/GOOGLE_SHEETS_SETUP.md`) — zero server,
   zero install, good as a lightweight backup.

See `docs/DESIGN.md` for the full architecture and how they fit together.

---

## Quick start (Python route)

```bash
# 1. Install (Python 3.10+)
pip install -r requirements.txt
pip install -e .
python -m playwright install chromium   # only if you use the scraper

# 2. Configure
cp .env.example .env          # then fill in what you have
#   -> at minimum: GOOGLE_SERVICE_ACCOUNT_JSON + GOOGLE_SHEET_NAME
#   See docs/GOOGLE_SHEETS_SETUP.md (about 15 min).

# 3. Define who to target
#   Edit config/campaigns.yaml (industries + cities).

# 4. Run the pipeline, stage by stage
python -m fixgenie.cli discover      # find businesses -> local staging DB
python -m fixgenie.cli enrich        # crawl their sites for email + owner
python -m fixgenie.cli validate      # email (syntax+MX) + phone (E.164)
python -m fixgenie.cli push          # de-dup + append to the Google Sheet

# 5. Send (always preview first!)
python -m fixgenie.cli outreach --dry-run   # shows exactly what would send
python -m fixgenie.cli outreach             # actually sends + logs to sheet

# Or everything at once:
python -m fixgenie.cli run-all --outreach --dry-run
```

Check progress any time:

```bash
python -m fixgenie.cli status
```

---

## Commands

| Command | What it does |
|---|---|
| `discover [--scrape]` | Find businesses for every target in `campaigns.yaml`. |
| `enrich` | Crawl each website for owner name + email; optional Hunter.io. |
| `validate` | Validate email (syntax + MX) and format phone to E.164. |
| `push` | Fuzzy de-dup against the sheet, append only new leads. |
| `outreach [--dry-run]` | Send the email sequence to eligible leads. |
| `unsubscribe --email X` | Add an address to the do-not-contact list. |
| `run-all [--outreach] [--dry-run]` | Full pipeline in order. |
| `status` | Show lead counts per stage + config summary. |

---

## Legal & compliance — read before sending

This system **can** send cold email legally, but only if you follow the rules.
Cold B2B email is permitted under **US CAN-SPAM**, but **Canada's CASL** is
much stricter and generally expects consent. **Every** email this system sends
includes your identity, a physical postal address, and a working unsubscribe
link — because that's legally required.

**Before your first real send, go through `docs/COMPLIANCE_CHECKLIST.md`.**
This is not legal advice; when in doubt, talk to a lawyer familiar with
anti-spam law.

---

## Project layout

```
fixgenie-outreach/
├── src/fixgenie/
│   ├── common/         # config, logging, the Lead model
│   ├── discovery/      # Overpass, Google Places, directory scraper
│   ├── enrichment/     # website crawler + Hunter.io
│   ├── validation/     # email + phone validators
│   ├── storage/        # SQLite staging, Google Sheets, dedup
│   ├── outreach/       # sender, templates engine, compliance
│   ├── pipeline.py     # orchestration of all stages
│   └── cli.py          # command-line interface
├── templates/          # Jinja2 email templates (3-step sequence)
├── config/campaigns.yaml   # WHO you target + HOW you reach out
├── n8n/                # importable no-code workflows
├── scripts/            # webhook service (n8n hybrid / ESP events)
├── docs/               # design, setup, compliance
├── tests/              # unit tests
└── .github/workflows/  # free scheduling via GitHub Actions
```

---

## Recommended rollout (from the requirements doc, Section 14)

1. **Foundation** — sheet + credentials working (`status` runs clean).
2. **Discovery** — `discover` pulls real businesses into staging.
3. **Enrichment & validation** — `enrich` + `validate` fill and clean.
4. **Storage** — `push` lands de-duped rows in the sheet.
5. **Outreach** — `outreach --dry-run` on 20–30 leads, review, then send.
6. **Compliance review** — walk the checklist, confirm unsubscribe works.
7. **Scale** — expand `campaigns.yaml`, schedule via GitHub Actions.

Start on free tiers. You only pay anything once you outgrow them.
