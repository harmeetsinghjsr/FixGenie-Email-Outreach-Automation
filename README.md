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
5. [Daily use: find → process → send](#daily-use)
6. [The cheat sheet](#cheat-sheet)
7. [Command reference](#command-reference)
8. [Project layout](#project-layout)
9. [Troubleshooting](#troubleshooting)
10. [Legal / compliance](#legal--compliance)

---

## How it works

```
   FIND LEADS            PROCESS THEM              SEND EMAILS
  ┌────────────┐   ┌──────────────────────┐   ┌──────────────────┐
  │ exa_leads  │ → │ enrich → validate →   │ → │  outreach        │
  │ (websearch)│   │ push (to Google Sheet)│   │ (dry-run → send) │
  └────────────┘   └──────────────────────┘   └──────────────────┘
```

- **Find** — search the web for a type of business and pull their email/phone/address.
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
| 8 | Hunter.io API key | free tier | finds/verifies extra emails | https://hunter.io/api-keys |
| 9 | Google Places API key | free $200/mo credit | extra local-business data | Google Cloud Console |

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

### Someone asks to stop

```bash
python -m fixgenie.cli unsubscribe --email someone@example.com
```

---

## Cheat sheet

```bash
# ONE-TIME setup
python -m venv .venv && source .venv/bin/activate   # (Windows: .venv\Scripts\activate)
pip install -r requirements.txt && pip install -e .
npm install -g mcporter
mcporter config add exa https://mcp.exa.ai/mcp --scope home
cp .env.example .env        # then fill it in + set up Google Sheet + domain auth

# EVERY campaign
python scripts/exa_leads.py --industry "real estate" --city "Miami" --region "Florida"
python -m fixgenie.cli enrich && python -m fixgenie.cli validate && python -m fixgenie.cli push
python -m fixgenie.cli outreach --dry-run     # preview
python -m fixgenie.cli outreach               # send for real
```

---

## Command reference

| Command | What it does |
|---|---|
| `python scripts/exa_leads.py --industry X [--city Y --region Z]` | Find leads (with emails) via Exa. Use `--query "..."` for a custom global search. |
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
scripts/exa_leads.py     ← the lead finder (Exa web search)
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
