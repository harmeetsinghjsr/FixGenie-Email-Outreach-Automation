# FixGenie — Lead Finder + Email Outreach

An almost-free, self-hosted system that:

1. **Finds business leads and their email addresses** by searching the web.
2. **Sends them a polite 3-email sequence automatically**, from your own domain.
3. **Tracks everything in a Google Sheet** that acts as your CRM.

You run a few commands in a terminal. Leads appear in your Google Sheet, and
emails go out on a schedule you control.

> This README is written so someone who just cloned the repo can go from
> **zero → sending** without getting stuck. Read it once, top to bottom.

---

## Table of contents

1. [How it works (the big picture)](#how-it-works)
2. [What you'll need (accounts & keys checklist)](#what-youll-need)
3. [Install](#install)
4. [Configure (.env + Google Sheet + email domain)](#configure)
5. [Daily use: one command, or step by step](#daily-use)
6. [Sheet maintenance (one-time fixers)](#sheet-maintenance-one-time-fixers)
7. [The cheat sheet](#cheat-sheet)
8. [Command reference](#command-reference)
9. [Project layout](#project-layout)
10. [Troubleshooting](#troubleshooting)
11. [Legal / compliance](#legal--compliance)

---

## How it works

```
 FIND LEADS      PERSONALIZE       PROCESS THEM            SEND EMAILS
┌───────────┐   ┌────────────┐   ┌──────────────────┐   ┌──────────────┐
│ exa_leads │ → │ personalize│ → │ enrich→validate→ │ → │  outreach    │
│(websearch)│   │  (LLM)     │   │ push (to Sheet)  │   │(dry-run→send)│
└───────────┘   └────────────┘   └──────────────────┘   └──────────────┘
```

- **Find** — search the web for a type of business and pull their email/phone/address.
- **Personalize** *(optional, recommended)* — an LLM writes a clean company name and a tailored one-line opener per lead, so emails read handwritten.
- **Process** — clean the data, verify the emails are real, save to your Sheet.
- **Send** — email a 3-step sequence, stop automatically on reply/unsubscribe, log every send.

---

## What you'll need

Because `.env` is **not** included in the repo (it holds secrets), you must
create your own accounts and paste your own keys. Here's the full checklist.
Items marked **required** are needed to run end to end; the rest are optional.

| # | Thing | Cost | Why you need it | Where to get it |
|---|---|---|---|---|
| 1 | **Python 3.10+** | free | runs the whole app | https://python.org |
| 2 | **Node.js (LTS)** | free | runs the lead-finder bridge | https://nodejs.org |
| 3 | **Google account + Google Sheet** | free | your CRM / lead storage | https://sheets.google.com |
| 4 | **Google Cloud service account** (JSON key) — *required* | free | lets the app write to your Sheet | https://console.cloud.google.com |
| 5 | **Exa web search** (via mcporter) — *required for finding leads* | free, **no key** | finds businesses + their emails | configured during install (below) |
| 6 | **An email sender** — *required for sending*: **Brevo** (recommended) or **Gmail** | free tiers | actually sends the emails | Brevo: https://app.brevo.com · Gmail app password: https://myaccount.google.com/apppasswords |
| 7 | **A domain you own** (e.g. `yourcompany.com`) + access to its DNS | — | send from your own address without bouncing | your domain registrar / Cloudflare |
| 8 | **LLM gateway** (for personalization) | cheap / free tiers | writes a clean name + tailored opener per lead | any Anthropic-Messages-format endpoint (e.g. api.anthropic.com, or a router) |
| 9 | Hunter.io API key | free tier | finds/verifies extra emails | https://hunter.io/api-keys |
| 10 | Google Places API key | free $200/mo credit | extra local-business data | Google Cloud Console |

**The three you cannot skip:** a Google service-account JSON (#4), Exa (#5,
free/no key), and one email sender with domain authentication (#6 + #7).

---

## Install

From a terminal, inside the project folder:

### 1. Python side

```bash
# (recommended) create a virtual environment
python -m venv .venv
# Windows:  .venv\Scripts\activate      |  macOS/Linux:  source .venv/bin/activate

pip install -r requirements.txt
pip install -e .
```

After `pip install -e .` you can run commands as either
`python -m fixgenie.cli <cmd>` or the shortcut `fixgenie <cmd>`.

### 2. Lead-finder side (Exa web search)

This is what makes the lead finder work. You need **Node.js** first
(`node --version` should print a version), then:

```bash
npm install -g mcporter
mcporter config add exa https://mcp.exa.ai/mcp --scope home
```

Check it worked:

```bash
mcporter list exa      # should show: exa (2 tools)
```

That's it — Exa needs **no API key**.

> The full explanation of these extra tools also lives in
> [`requirements.txt`](requirements.txt).

---

## Configure

### A. Create your `.env`

```bash
cp .env.example .env
```

Then open `.env` and fill in your values. Every key is explained in
[`.env.example`](.env.example). The important ones:

| Key | What to put |
|---|---|
| `GOOGLE_SERVICE_ACCOUNT_JSON` | path to your Google key file (default `./config/service_account.json`) |
| `GOOGLE_SHEET_NAME` | the exact name of your Google Sheet |
| `EMAIL_PROVIDER` | `brevo` or `gmail` |
| `BREVO_API_KEY` | your Brevo **API** key (starts with `xkeysib-`) |
| `GMAIL_ADDRESS` / `GMAIL_APP_PASSWORD` | only if using Gmail |
| `HUNTER_API_KEY` | optional, boosts email finding |
| `SENDER_NAME` / `SENDER_COMPANY` / `SENDER_EMAIL` | your identity in the email footer |
| `SENDER_POSTAL_ADDRESS` | a **real** postal address (legally required in every email) |
| `UNSUBSCRIBE_BASE_URL` | where unsubscribe links point |
| `DAILY_SEND_LIMIT` | max emails per run (start small, e.g. 20–30) |

### B. Set up the Google Sheet (your CRM)

1. Create a blank spreadsheet at https://sheets.google.com and name it exactly
   what you put in `GOOGLE_SHEET_NAME` (e.g. `FixGenie Leads Master`). You don't
   need to add columns — the app creates them.
2. In https://console.cloud.google.com create a project, then **enable** both
   **Google Sheets API** and **Google Drive API**.
3. Create a **Service Account**, then **Keys → Add Key → JSON**. Save the
   downloaded file as `config/service_account.json`.
4. Open the JSON, copy the `client_email` (looks like
   `...@...iam.gserviceaccount.com`), then in your Sheet click **Share** and add
   that email as **Editor**.

Full walkthrough: [`docs/GOOGLE_SHEETS_SETUP.md`](docs/GOOGLE_SHEETS_SETUP.md).

### C. Authenticate your sending domain (do this or emails bounce)

If you send from `you@yourcompany.com`, your domain's security (DMARC) will
**reject** mail unless you authorize Brevo. This is a one-time DNS setup.

**Using Brevo:**
1. In Brevo → **Settings → Senders, Domains & Dedicated IPs → Domains**, add
   your domain (e.g. `yourcompany.com`).
2. Brevo shows you DNS records — usually two `CNAME` records
   (`brevo1._domainkey`, `brevo2._domainkey`) and one `TXT` (`brevo-code:...`).
3. Add those records in your DNS provider (Cloudflare, GoDaddy, etc.).
   **On Cloudflare, set the CNAMEs to "DNS only" (grey cloud), not proxied.**
4. Back in Brevo, click **Authenticate**. Wait a few minutes for DNS to
   propagate.
5. Also add your sending address as a **verified sender** in Brevo.

> **Brevo "unrecognised IP" error?** Brevo can block API calls from new IPs.
> Fix it in **Settings → Security → Authorized IPs** (add the IP, or disable the
> restriction).

**Using Gmail instead:** enable 2FA on the account, create an **App Password**
at https://myaccount.google.com/apppasswords, and put it in `GMAIL_APP_PASSWORD`
(set `EMAIL_PROVIDER=gmail`). Gmail is easier to start with but sends from a
`@gmail.com`-style path and is better for low volume.

### D. Confirm everything is wired up

```bash
python -m fixgenie.cli status
```

This prints your lead counts and shows which provider + integrations are active.

---

## Daily use

### The easy way — one command does everything

If you just want it to run, double-click **`scripts/run_all.bat`** (or run it
from a terminal). It does the whole pipeline on your PC, in order, and writes a
log to `data/run_all.log`:

```
1. find new leads (Exa)
2. AI-personalize each one (clean name + 3 tailored openers)
3. enrich → validate → push to your Google Sheet
4. send today's emails + follow-ups (respects DAILY_SEND_LIMIT)
```

```bash
scripts\run_all.bat
```

That's the normal way to use FixGenie now — **everything runs locally on your
PC.** Run it whenever you like (once a day, or a few times a week is plenty).
Every email is AI-written, and follow-ups (steps 2 & 3) go out automatically to
leads who are due.

> **Why local and not the cloud?** Lead-finding (Exa) and AI personalization are
> blocked from GitHub's datacenter IPs, so the cloud can only *send* — it can't
> find or personalize. Rather than send half-baked emails, the daily cloud
> schedule is turned **off** and `run_all.bat` does the complete job on your PC.
> (See [Full automation](#full-automation-github-actions) if you ever want the
> cloud send-only job back.)

### Check progress any time

```bash
python scripts/progress.py
```

A read-only dashboard of the whole campaign: how many leads you have, how many
are emailable/Valid, how many have their AI hooks, where everyone is in the
sequence, and how many are ready to send next. It never changes or sends
anything, so it's always safe to run.

---

### The manual way — step by step

Prefer to run each stage yourself? Here are the individual steps `run_all.bat`
performs.

### Step 1 — Find leads

The lead finder is `scripts/exa_leads.py`. Three ways to use it:

```bash
# Local businesses in a city
python scripts/exa_leads.py --industry "real estate" --city "Miami" --region "Florida"

# A type of company, worldwide (no city)
python scripts/exa_leads.py --industry "SaaS company"

# Write your own search (most control)
python scripts/exa_leads.py --query "AI automation startups in Europe hiring"
```

It prints how many leads it found and how many have an email, then stages them.

> Tip: local small businesses usually list a direct email. Big global companies
> often hide behind contact forms, so email hit-rate is lower for "big" targets.

#### Want hundreds of leads at once?

`scripts/bulk_find.py` runs the finder across a whole list of (industry, city)
targets in one go:

```bash
python scripts/bulk_find.py --num 8
```

To change who it goes after, edit the **`TARGETS`** list at the top of
[scripts/bulk_find.py](scripts/bulk_find.py) — each line is
`("industry", "city", "region", "country")`. One run can stage a few hundred
leads. Then personalize and process them exactly like a normal batch (below).

### Step 1.5 — Personalize (optional, recommended)

Makes every email read handwritten instead of templated. Requires the LLM keys
in `.env` (`LLM_BASE_URL`, `LLM_API_KEY`, `LLM_MODEL`).

```bash
python scripts/personalize.py
```

For each staged lead, an LLM writes a **clean company name** (fixing scraped
junk like "Start the Conversation") and a **tailored one-line opener** that
references what the business actually does. These become the name and first line
of the email. Skip this step and the emails still send — just less specific.

### Step 2 — Process leads into your Sheet

Run these three (you can paste as one line):

```bash
python -m fixgenie.cli enrich && python -m fixgenie.cli validate && python -m fixgenie.cli push
```

- **enrich** — visits each site to add an owner/contact name (uses Hunter.io if configured).
- **validate** — checks each email is real; good ones = **Valid**, generic `info@` = **Risky**.
- **push** — de-duplicates and appends clean leads to your Google Sheet.

Open your Sheet — the leads are there.

### Step 3 — Send the outreach

**Always preview first (nothing sends):**

```bash
python -m fixgenie.cli outreach --dry-run
```

This lists exactly who *would* be emailed and the subject lines. When it looks right:

```bash
python -m fixgenie.cli outreach
```

This sends the first email to every **Valid** lead, waits ~45s between each,
stops at your `DAILY_SEND_LIMIT`, and logs each send to the Sheet's
**Outreach Log** tab.

### Follow-ups

Run `outreach` again on later days. It automatically sends step 2 (after 3 days)
and step 3 (after 7 days) only to leads who are due, and **stops the sequence**
for anyone who replies, unsubscribes, or bounces.

The follow-ups are **also AI-personalized**: the `personalize` step writes a
distinct opener for each of the 3 emails (intro, follow-up, breakup), so step 2
and step 3 aren't copy-paste — each references the specific business too.

### Automate the daily send (so follow-ups happen hands-off)

With a big lead list, you don't want to run `outreach` by hand every day. Two
free options:

**Option A — Windows Task Scheduler (local).** Run this once to send every
weekday morning using the included `scripts/run_outreach.bat` (which also writes
a local log to `data/outreach_cron.log`):

```bash
schtasks /Create /TN "FixGenie Outreach" /TR "\"C:\Users\hs978\CodeSpace\FixGenie\FixGenie Email Outreach Automation\scripts\run_outreach.bat\"" /SC WEEKLY /D MON,TUE,WED,THU,FRI /ST 08:52
```

To stop it later: `schtasks /Delete /TN "FixGenie Outreach" /F`.

**Option B — GitHub Actions (fully hands-off, in the cloud).** See
[**Full automation**](#full-automation-github-actions) below — it runs the
*entire* pipeline (find → personalize → push → outreach + follow-ups) on a daily
schedule, even when your PC is off.

Each run sends up to `DAILY_SEND_LIMIT` (in `.env`) — keep it modest (e.g. 30)
so a big list goes out gradually and your sending domain stays trusted.

### Someone asks to stop

```bash
python -m fixgenie.cli unsubscribe --email someone@example.com
```

---

## Sheet maintenance (one-time fixers)

Handy scripts for keeping the Google Sheet clean. They talk to the sheet
directly, so they also fix leads that were added straight to the sheet (not
through the local pipeline).

### Fill in missing AI pitch hooks

If some leads have an email but blank **Pitch Hook** columns (W/X/Y), this asks
your LLM for the 3 openers and writes them straight back into the sheet.

```bash
python scripts/fill_hooks.py --dry-run    # show what WOULD change, write nothing
python scripts/fill_hooks.py              # fill everything missing
python scripts/fill_hooks.py --limit 20   # just the first 20 (test run)
```

Needs the `LLM_*` keys in `.env`.

### Remove un-emailable, never-contacted rows

Clears out junk rows that can never be emailed — leads with **no email address**
that were **never contacted**. It is deliberately cautious: it will **never**
touch a lead that has a real email, or one that has already been sent.

```bash
python scripts/clean_rows.py --dry-run    # list exactly what would be removed
python scripts/clean_rows.py              # remove them (permanent on the sheet)
```

Always run `--dry-run` first and eyeball the list before deleting.

---

## Full automation (GitHub Actions)

> **Currently OFF by design.** The daily `cron` schedule in
> [.github/workflows/pipeline.yml](.github/workflows/pipeline.yml) is commented
> out, and the cloud job is **send-only** (it can't find leads or personalize —
> those are blocked from GitHub's IPs). The normal way to run FixGenie is
> [`scripts/run_all.bat`](#the-easy-way--one-command-does-everything) on your PC.
> The rest of this section is only if you want to re-enable a cloud send.

Want a cloud job that just **sends** outreach + follow-ups on a schedule (even
when your PC is off)? Re-enable it by uncommenting the `schedule: cron` block in
the workflow file. It reads whatever leads are already in your Sheet and sends
to the **Valid** ones — you still find + personalize leads locally first.

### Setup (once)

1. Push this repo to GitHub (your `.env` and `config/service_account.json` stay
   local — they're git-ignored — so you re-supply them as **secrets**).
2. In GitHub: **Settings → Secrets and variables → Actions → New repository
   secret**, and add each of these:

   | Secret | Value |
   |---|---|
   | `GOOGLE_SERVICE_ACCOUNT_JSON` | the full contents of your `config/service_account.json` |
   | `GOOGLE_SHEET_NAME` | `FixGenie Leads Master` |
   | `EMAIL_PROVIDER` | `brevo` |
   | `BREVO_API_KEY` | your `xkeysib-…` key |
   | `SENDER_NAME`, `SENDER_COMPANY`, `SENDER_EMAIL`, `SENDER_POSTAL_ADDRESS` | your identity |
   | `UNSUBSCRIBE_BASE_URL` | your unsubscribe URL |
   | `LLM_BASE_URL`, `LLM_API_KEY`, `LLM_MODEL` | your personalization gateway |
   | `HUNTER_API_KEY` | optional (leave unset to keep Hunter off) |

3. That's it. It runs on the schedule. To run it on demand, use **Actions → FixGenie Daily Pipeline → Run workflow** (there's a checkbox to send only, skipping discovery).

### Which automation should I use?

| | Local (Task Scheduler) | GitHub Actions |
|---|---|---|
| Runs when PC is off | ❌ | ✅ |
| Setup | 1 command | add ~12 secrets |
| Finds new leads daily too | only outreach | ✅ full pipeline |
| Good for | quick start | true hands-off |

> Heads-up: once automated, emails send without a manual `--dry-run` check, so
> make sure you're happy with the templates and targets first. The daily cap and
> the auto-stop on replies/unsubscribes/bounces are your safety rails.

---

## Cheat sheet

```bash
# ONE-TIME setup
python -m venv .venv && source .venv/bin/activate   # (Windows: .venv\Scripts\activate)
pip install -r requirements.txt && pip install -e .
npm install -g mcporter
mcporter config add exa https://mcp.exa.ai/mcp --scope home
cp .env.example .env        # then fill it in + set up Google Sheet + domain auth

# EVERYDAY: the one-click way (find -> personalize -> push -> send + follow-ups)
scripts\run_all.bat

# Check progress any time (read-only, safe)
python scripts/progress.py

# --- or run the stages by hand ---
python scripts/exa_leads.py --industry "real estate" --city "Miami" --region "Florida"
python scripts/personalize.py                 # optional: handwritten-quality emails
python -m fixgenie.cli enrich && python -m fixgenie.cli validate && python -m fixgenie.cli push
python -m fixgenie.cli outreach --dry-run     # preview
python -m fixgenie.cli outreach               # send for real

# BULK: hundreds of leads at once (edit TARGETS inside bulk_find.py first)
python scripts/bulk_find.py --num 8
python scripts/personalize.py
python -m fixgenie.cli enrich && python -m fixgenie.cli validate && python -m fixgenie.cli push

# SHEET MAINTENANCE (dry-run first!)
python scripts/fill_hooks.py --dry-run        # fill missing AI pitch hooks
python scripts/clean_rows.py --dry-run        # remove un-emailable, never-contacted rows
```

> For big batches, set `crawl_website: false` and `use_hunter: false` in
> `config/campaigns.yaml` (Exa already has the emails), and keep
> `DAILY_SEND_LIMIT` modest (~40) so the list sends gradually.

---

## Command reference

| Command | What it does |
|---|---|
| `scripts\run_all.bat` | **The one-click runner.** Find → personalize → enrich → validate → push → send + follow-ups, all on your PC. Logs to `data/run_all.log`. |
| `python scripts/progress.py` | Read-only dashboard: lead counts, email quality, outreach funnel, what's ready to send. Changes nothing. |
| `python scripts/exa_leads.py --industry X [--city Y --region Z]` | Find leads (with emails) via Exa. Use `--query "..."` for a custom global search. |
| `python scripts/bulk_find.py [--num N]` | Find leads across MANY targets at once (edit the `TARGETS` list inside it). |
| `python scripts/personalize.py [--limit N]` | LLM-write a clean name + tailored opener per staged lead. Needs `LLM_*` in `.env`. |
| `python scripts/fill_hooks.py [--dry-run] [--limit N]` | Fill missing AI pitch hooks (W/X/Y) straight into the sheet. Needs `LLM_*` in `.env`. |
| `python scripts/clean_rows.py [--dry-run]` | Remove un-emailable, never-contacted junk rows from the sheet. Never touches sent or emailable leads. |
| `scripts/run_outreach.bat` | Windows batch file that runs `outreach` + logs to `data/outreach_cron.log`. Point Task Scheduler at it. |
| `fixgenie status` | Show lead counts per stage + which integrations are active. |
| `fixgenie enrich [--limit N]` | Add contact names / more emails to staged leads. |
| `fixgenie validate [--limit N]` | Verify emails (syntax + mail server) and format phones. |
| `fixgenie push [--limit N]` | De-dup and append clean leads to the Google Sheet. |
| `fixgenie outreach --dry-run` | Preview the emails that would send. **No email sent.** |
| `fixgenie outreach [--limit N]` | Send the sequence to eligible leads. |
| `fixgenie unsubscribe --email X` | Add an address to the do-not-contact list. |
| `fixgenie discover [--scrape]` | (Legacy) find businesses via free OpenStreetMap. Rarely returns emails — prefer `exa_leads.py`. |
| `fixgenie import-excel --file X.xlsx` | Import already-scraped leads from a spreadsheet. |
| `fixgenie run-all [--outreach] [--dry-run]` | Run discover → enrich → validate → push (→ outreach). |

(`fixgenie <cmd>` and `python -m fixgenie.cli <cmd>` are equivalent.)

---

## Project layout

```
scripts/run_all.bat      ← ONE-CLICK runner: find → personalize → push → send (+ log)
scripts/progress.py       ← read-only campaign dashboard (safe to run any time)
scripts/exa_leads.py     ← the lead finder (Exa web search)
scripts/bulk_find.py     ← find leads across many industries/cities at once (edit TARGETS)
scripts/personalize.py   ← optional LLM step: clean name + tailored opener per lead
scripts/fill_hooks.py    ← one-time: fill missing AI pitch hooks straight into the sheet
scripts/clean_rows.py    ← one-time: remove un-emailable, never-contacted rows
scripts/run_outreach.bat ← daily send-only runner for Windows Task Scheduler
config/campaigns.yaml    ← email sequence + targeting/enrichment options
config/service_account.json  ← your Google key (you provide; gitignored)
templates/               ← the actual email wording (edit to sound like you)
.env                     ← your keys + sender identity + limits (you create; gitignored)
.env.example             ← template for .env (safe to commit)
data/staging.db          ← local scratch DB (leads before they reach the Sheet)
docs/                    ← setup + compliance guides
src/fixgenie/            ← the engine (you don't need to open this)
```

---

## Troubleshooting

| Symptom | Fix |
|---|---|
| **`Spreadsheet 'X' not found`** | Sheet name in `.env` must match exactly, and it must be **shared as Editor** with the service account's `client_email`. Ensure Google **Drive API** is enabled. |
| **`mcporter not found`** | Install it: `npm install -g mcporter` (needs Node.js), then `mcporter config add exa https://mcp.exa.ai/mcp --scope home`. |
| **`exa_leads.py` finds few emails** | Big/global targets hide emails behind forms. Try a `--city` search or a more specific `--query`. Turn on Hunter.io for more coverage. |
| **Emails bounce with `DMARC` / `5.7.26`** | Your sending domain isn't authenticated. Do [Configure → C](#c-authenticate-your-sending-domain-do-this-or-emails-bounce). |
| **Brevo `unrecognised IP` (401)** | Authorize the IP in Brevo **Settings → Security → Authorized IPs**, or disable that restriction. |
| **First email lands in Spam** | Normal for a brand-new sending domain. Warm up slowly (low `DAILY_SEND_LIMIT`), keep DKIM/DMARC valid. |
| **`discover` returns 0** | The industry keyword must match a mapping (e.g. use `real estate`, not `real estate agent`), or just use `exa_leads.py`. |
| **`personalize.py` says "LLM not configured"** | Set `LLM_BASE_URL` + `LLM_API_KEY` in `.env`. |
| **personalize gets 401 "unauthorized client"** | Your gateway checks the client identity — keep `LLM_USER_AGENT=claude-cli/1.0.60 (external)` (or whatever your provider requires). |

---

## Legal / compliance

Cold **B2B** email is legal in many places if you follow the rules: every email
must include your real identity, a physical postal address, and a working
unsubscribe link — all of which this tool adds automatically. Rules vary by
country (US CAN-SPAM is permissive; Canada's CASL is strict and often expects
consent). **Before your first real send, read
[`docs/COMPLIANCE_CHECKLIST.md`](docs/COMPLIANCE_CHECKLIST.md).** This is not
legal advice.

---

## A note on security

Never commit `.env` or `config/service_account.json` — they hold secrets and are
already in `.gitignore`. If you fork/share this repo, double-check they're not
included.
