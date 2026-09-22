# FixGenie Outreach System — Design & Architecture

This document explains *how* the system is built and *why* each decision was
made, so any developer (or future you) can extend it confidently. It maps
directly to the phases in the requirements pack.

---

## 1. Design goals

1. **Near-zero cost.** Every default is a free tier or open-source tool. Paid
   services (Google Places, Hunter.io) are optional boosters, never required.
2. **Legal by default.** Compliance isn't a feature you turn on — the required
   footer, unsubscribe link, and suppression list are baked into the send path
   so it's hard to send a non-compliant message by accident.
3. **One schema, three engines.** The Python pipeline, n8n workflows, and Apps
   Script all read/write the *same* Google Sheet schema, so you can start
   no-code and graduate to code without a migration.
4. **Resilient and re-runnable.** Raw discovery is staged locally first, so
   enrichment/validation can re-run without re-hitting any source.

---

## 2. Data flow

```
                    ┌─────────────┐
   campaigns.yaml → │  DISCOVERY  │  Overpass (free) + Places (optional) + scraper
                    └──────┬──────┘
                           ▼
                    ┌─────────────┐   SQLite staging DB (data/staging.db)
                    │   staging   │   stage = 'new'
                    └──────┬──────┘
                           ▼
                    ┌─────────────┐
                    │  ENRICHMENT │  crawl website → owner name, email, phone
                    └──────┬──────┘   stage = 'enriched'
                           ▼
                    ┌─────────────┐
                    │ VALIDATION  │  email syntax+MX, phone→E.164, role→Risky
                    └──────┬──────┘   stage = 'validated'
                           ▼
                    ┌─────────────┐
                    │ DEDUP+PUSH  │  rapidfuzz vs Sheet → append new only
                    └──────┬──────┘   stage = 'pushed'  →  GOOGLE SHEET (CRM)
                           ▼
                    ┌─────────────┐
                    │  OUTREACH   │  render → footer → send → update status
                    └──────┬──────┘
                           ▼
                    ┌─────────────┐
                    │  TRACKING   │  ESP webhook → opens/bounces/unsubs → Sheet
                    └─────────────┘
```

The **Google Sheet is the source of truth** for the team's view. The **SQLite
DB is a staging/scratch layer** — it exists so scraping and API calls are
batched and re-runnable, not to duplicate the CRM.

---

## 3. Component responsibilities

### Discovery (`src/fixgenie/discovery/`)
Every source implements one interface (`DiscoverySource.search(target)`), so
the pipeline treats them interchangeably.

- **`overpass_source.py` — primary.** Geocodes the city via Nominatim, builds
  an Overpass QL query from an industry→OSM-tag map, parses POIs into `Lead`s.
  Free, unlimited, legal (ODbL open data).
- **`places_source.py` — optional booster.** Google Places Text Search (new v1
  API). Runs only if a key is set. Lowest-risk paid-ish source (official API).
- **`directory_scraper.py` — opt-in.** Playwright-based, generic
  `SelectorProfile` so it adapts to a specific directory without touching crawl
  logic. Ships with *politeness* (delays, real UA, robots.txt awareness), not
  evasion. Never in the default source list because of ToS risk.

**Why Overpass over scraping Google Maps?** The requirements doc flags Google
Maps/LinkedIn/Yelp scraping as a ToS/enforcement flashpoint (Section 6).
Overpass sidesteps that entirely: it's open data published for reuse.

### Enrichment (`src/fixgenie/enrichment/`)
- **`WebsiteCrawler`** fetches the homepage + likely contact/about pages, then
  extracts emails (regex, preferring the business's own domain), owner names
  (heuristic patterns like "founded by X", "X, Owner"), and a phone if missing.
  Prefers a *personal* email over a *role* email.
- **`HunterEnricher`** (optional) fills email/owner from the domain via
  Hunter.io's free tier when the crawler comes up empty.

### Validation (`src/fixgenie/validation/`)
- Email: `email-validator` for syntax + a live **MX DNS lookup** for
  deliverability (the free stand-in for ZeroBounce). Role emails (`info@`,
  `sales@`) are downgraded to **Risky** per the CASL note — we store them but
  don't send to them by default.
- Phone: `phonenumbers` → E.164, with a CA/US region hint from the city.
- Result is written to the `Email Verification Status` column (Valid / Risky /
  Invalid / Unknown).

### Storage (`src/fixgenie/storage/`)
- **`staging_db.py`** — SQLite wrapper keyed by a deterministic `lead_id`
  (hash of name+city+phone). This is the cheap exact-match dedup layer.
- **`dedup.py`** — `rapidfuzz` fuzzy layer: catches "Joe's Plumbing" vs "Joes
  Plumbing Inc", or rows sharing a phone/email/domain, before pushing.
- **`sheets.py`** — `gspread` client. Reads the whole Leads tab once and caches
  a `lead_id → row` index so status updates don't cost one API call per row
  (Sheets quota is ~60 reads/min). Two tabs: `Leads` + `Outreach Log`.

### Outreach (`src/fixgenie/outreach/`)
- **`compliance.py`** — suppression list (plain-text, auditable), per-recipient
  unsubscribe link, and the required legal footer (text + minimal HTML).
- **`senders.py`** — `GmailSMTPSender` and `BrevoSender` behind one interface.
  Chosen via `EMAIL_PROVIDER`.
- **`engine.py`** — the brain. Decides which cadence step each lead is due for
  (respecting `wait_days`), renders the Jinja2 template + footer, enforces the
  daily cap and human-like delays, skips suppressed/invalid leads, updates
  status, and writes an audit event. Takes a `persist` callback so it works
  identically against Sheets or the DB (and is unit-testable).

---

## 4. The "auto-email on storage" requirement (doc Sections 17–22)

The doc adds a key requirement: when a lead is stored, its first email should
fire automatically. We support all three patterns from Section 17:

| Pattern | How to use it here | Best for |
|---|---|---|
| **A — Inline** | `run-all --outreach` sends in the same run after push. | Bootstrap, low volume. |
| **B — Sheet polling** | The n8n `fixgenie_outreach_on_new_row.json` workflow, or the Apps Script trigger. | Most teams. |
| **C — DB trigger + webhook** | `scripts/webhook_service.py` exposes `/outreach/run`; point a Supabase/Postgres insert webhook or an n8n HTTP node at it. | Growth/scale. |

The schema carries the Section 22 tracking fields (`auto_email_sent`,
`auto_email_sent_at`, `send_attempts`, `send_error`, `template_version`,
`sequence_step`) so duplicate sends are impossible and retries are capped.

---

## 5. The hybrid architecture (doc's recommended path)

The doc recommends a **hybrid**: n8n for orchestration/scheduling + a small
Python service for heavy logic. That's exactly what `scripts/webhook_service.py`
enables:

```
n8n (schedule + Sheets writes)  ──HTTP──►  webhook_service.py  ──►  Python
   discovery / trigger                     /outreach/run           send engine
        ▲                                        │
        └──────────── Google Sheet ◄─────────────┘  (status synced back)
```

You get n8n's visual scheduling and the Python engine's dedup/validation/
compliance in one system, with no vendor lock-in.

---

## 6. Scheduling options (all free)

- **GitHub Actions** (`.github/workflows/pipeline.yml`) — discovery nightly,
  outreach weekday mornings. 2,000 free minutes/month.
- **cron** on any machine — `0 6 * * * cd /path && python -m fixgenie.cli run-all`.
- **n8n Schedule Trigger** — if you run the no-code path.

---

## 7. Security & data handling (doc Section 13)

- Secrets live in `.env` / GitHub Secrets / n8n's credential vault — never in
  code. `.gitignore` blocks `.env` and `service_account.json`.
- The Google service account is scoped to the single shared sheet, not Drive.
- The `Source URL` column keeps an audit trail so any lead can be traced and
  removed on request.
- The suppression list guarantees opt-outs are honored across every run.
- The webhook service requires a token and warns loudly if run without one.

---

## 8. Extending the system

- **New industry** → add a keyword→OSM-tag mapping in
  `overpass_source._INDUSTRY_TAGS`.
- **New region** → just add a target in `campaigns.yaml`; geocoding is automatic.
- **New directory to scrape** → fill a `SelectorProfile` and register a
  `DirectoryScraper` in `pipeline._build_sources`.
- **New email step** → add a template in `templates/` and a step in the
  `outreach.sequence` list in `campaigns.yaml`.
- **SMS follow-up (optional)** → add a `TwilioSender`-style class alongside the
  email senders; the doc notes TCPA/CRTC rules make manual calls to published
  business lines lower-risk than blasted SMS, so this is intentionally left as
  an opt-in extension rather than a default.
- **Real dashboard later** → the Sheet + `leads` schema map cleanly onto the
  Next.js + Supabase stack in doc Section 18 when you outgrow Sheets.

---

## 9. What this intentionally does *not* do

- It does not scrape Google Maps/LinkedIn/Yelp by default (ToS risk).
- It does not send to `Risky`/`Invalid`/role emails by default.
- It does not build its own open-tracking pixel — you use your ESP's built-in
  tracking (doc Section 11) to avoid deliverability harm.
- It does not promise 100% email accuracy — free MX validation removes the
  biggest bounce source but can't confirm every individual mailbox.
