# FixGenie Email Outreach Automation — How It Works

A plain-language guide to what this system does, how the pieces fit together, and
exactly how to run it — step by step. Anyone on the team should be able to follow
this without having built it.

---

## 1. What this system is (in one paragraph)

It's a free, self-hosted machine for cold B2B outreach. You give it a list of
businesses (either freshly discovered, or imported from a spreadsheet you already
have). It finds each business's email, checks the email and phone are real,
removes duplicates, saves everything into a Google Sheet that acts as your CRM,
and then sends a short, personalized 3-email sequence — logging every result back
to the sheet. It runs on free tools (target cost ≈ $0/month).

---

## 2. The pipeline — six stages

Think of a lead moving along a conveyor belt. Each stage does one job and hands
the lead to the next.

```
 IMPORT / DISCOVER  →  ENRICH  →  VALIDATE  →  DE-DUP + STORE  →  OUTREACH  →  TRACK
   (get businesses)   (find      (is the      (no duplicates,    (send the   (opens,
                        email)    email/phone   save to Sheet)    emails)     replies,
                                  real?)                                      unsubs)
```

| Stage | What happens | The command |
|---|---|---|
| **Import / Discover** | Load businesses — from your Excel file, or by searching OpenStreetMap/Google Places. | `import-excel` or `discover` |
| **Enrich** | Visit each business's website and pull out an email address + owner name. | `enrich` |
| **Validate** | Check the email is real (syntax + mail server exists) and format the phone. | `validate` |
| **De-dup + Store** | Remove duplicates, then append clean leads to the Google Sheet. | `push` |
| **Outreach** | Send the personalized email sequence to leads with a valid email. | `outreach` |
| **Track** | Opens/replies/bounces/unsubscribes flow back into the sheet. | (automatic via ESP) |

Behind the scenes, leads are staged in a small local database (`data/staging.db`)
as they move through Import → Enrich → Validate. Only clean, de-duplicated leads
get written to Google Sheets at the **push** step. This keeps the Sheet tidy and
avoids hitting Google's rate limits.

---

## 3. IMPORTANT: what your current Excel data means for email

Your file `data/US_RealEstate_Logistics_Leads.xlsx` was analyzed. Here's the
reality, so there are no surprises:

- **309 unique businesses**, every one with a **phone number**.
- **0 have a real email address** — every Email cell says *"Not public – website
  contact form."* That's not an email, so the system treats it as blank.
- **Only 37 have a usable website** the system could crawl to *find* an email.

**What this means:**

> This dataset is built for **phone/call outreach**, not email. To do *email*
> automation on it, the system must first **find** emails. It can only realistically
> do that for the ~37 leads that have a website (via the Enrich stage). The other
> ~272 are phone-only until you add websites/emails for them.

You have three honest options for the email side (details in Section 6):
1. **Enrich the 37** with websites and email just those — small but legitimate.
2. **Discover fresh leads** with the built-in OpenStreetMap/Places discovery,
   which returns websites you can then enrich into emails.
3. **Use the data as intended — for calling** — and keep the `Call Tracker` sheet
   as your workflow (the system's email engine simply won't have addresses to use).

The system supports all three; it just can't invent email addresses that aren't
findable.

---

## 4. One-time setup (do this first)

You only do this once.

### 4.1 Install
```bash
cd "FixGenie Email Outreach Automation"
pip install -r requirements.txt
pip install -e .
python -m playwright install chromium     # only if you'll use the directory scraper
```

### 4.2 Connect Google Sheets (your CRM)
Follow **`docs/GOOGLE_SHEETS_SETUP.md`** (about 15 minutes). At the end you'll have:
- a Google Sheet named `FixGenie Leads Master`,
- a `config/service_account.json` credentials file,
- the sheet shared with that service account.

### 4.3 Set your secrets
```bash
cp .env.example .env
```
Open `.env` and fill in at least:
- `GOOGLE_SERVICE_ACCOUNT_JSON` and `GOOGLE_SHEET_NAME`
- your sending account: either `GMAIL_ADDRESS` + `GMAIL_APP_PASSWORD`
  (a Gmail *App Password*, not your login), or a `BREVO_API_KEY`
- `SENDER_NAME`, `SENDER_COMPANY`, `SENDER_EMAIL`, and — legally required —
  a real `SENDER_POSTAL_ADDRESS`.

> The postal address and an unsubscribe link are **legally required** in every
> commercial email. The system adds them automatically, but the address must be
> real. See `docs/COMPLIANCE_CHECKLIST.md`.

---

## 5. How to run it — the everyday workflow

Check where things stand at any time:
```bash
python -m fixgenie.cli status
```

### 5.1 Path A — Use your existing Excel leads

```bash
# 1) Import the spreadsheet into staging
python -m fixgenie.cli import-excel --file "data/US_RealEstate_Logistics_Leads.xlsx"

# 2) Find emails by crawling each business website (fills the ~37 that have sites)
python -m fixgenie.cli enrich

# 3) Validate emails (syntax + mail-server check) and format phones
python -m fixgenie.cli validate

# 4) De-duplicate and write clean leads into the Google Sheet
python -m fixgenie.cli push

# 5) PREVIEW the emails first — this sends nothing:
python -m fixgenie.cli outreach --dry-run

# 6) When the preview looks right, actually send:
python -m fixgenie.cli outreach
```

By default only leads with a **Valid** email are emailed (role addresses like
`info@` are marked *Risky* and skipped). So on your current data, step 6 will
email only the handful the enrichment step managed to find — which is exactly
what you want for a clean, compliant start.

### 5.2 Path B — Discover fresh leads (that come with websites)

Edit `config/campaigns.yaml` to set your target industries + cities, then:
```bash
python -m fixgenie.cli run-all --dry-run          # discover→enrich→validate→push, preview outreach
python -m fixgenie.cli run-all --outreach         # the whole thing, for real
```

### 5.3 Import only specific sheets
```bash
python -m fixgenie.cli import-excel --file "data/US_RealEstate_Logistics_Leads.xlsx" --sheet "Leads"
```

---

## 6. Getting emails for phone-only leads (the enrichment reality)

The Enrich stage is where emails come from. For each lead with a website it:
1. opens the homepage plus likely pages (`/contact`, `/about`, `/team`),
2. extracts email addresses (preferring ones on the business's own domain),
3. tries to spot the owner's name,
4. records what it found in the lead's Notes for auditing.

If a lead has **no website**, there is nothing to crawl, so it stays without an
email. To improve email coverage you can:
- **Add website URLs** into the Excel `Website` column (even a quick manual pass on
  the top targets), then re-import + re-enrich.
- **Turn on Hunter.io** (free tier, 25 lookups/month): set `HUNTER_API_KEY` in
  `.env` and `use_hunter: true` in `campaigns.yaml`. It finds emails from a domain.
- **Use discovery** (Path B), which pulls in businesses that already have websites.

---

## 7. What the Google Sheet looks like

Two tabs are created automatically:

- **`Leads`** — one row per business, with columns for name, contact, category,
  email, phone, website, address, city, source, verification status, outreach
  status, last-contacted date, and internal tracking fields.
- **`Outreach Log`** — an append-only record of every send/open/bounce event, with
  timestamps, so you always have an audit trail.

`Outreach Status` moves through: `Not Contacted → Sent → Opened → Replied`, or
`Bounced` / `Unsubscribed`. The system never re-emails someone who replied,
unsubscribed, or bounced.

---

## 8. Sending automatically (optional)

Three ways to make it hands-off — pick one:

1. **Scheduled (simplest to reason about):** the included GitHub Actions workflow
   (`.github/workflows/pipeline.yml`) runs discovery nightly and outreach on
   weekday mornings, free.
2. **Auto-email when a lead is added:** the n8n workflow
   `n8n/fixgenie_outreach_on_new_row.json` watches the sheet and emails each new
   valid lead automatically. (Also a no-server Google Apps Script version in
   `docs/GOOGLE_SHEETS_SETUP.md`.)
3. **On-demand trigger:** run `scripts/webhook_service.py` and have n8n or another
   system POST to `/outreach/run`.

---

## 9. Staying legal (read before your first real send)

Cold B2B email is allowed in the US under CAN-SPAM, and Canada's CASL is stricter
(generally expects consent). The system bakes in the required pieces — sender
identity, physical address, working unsubscribe, and a permanent do-not-contact
list — but you're responsible for using it properly.

**Before sending, walk through `docs/COMPLIANCE_CHECKLIST.md`.** Key rules:
- Only email publicly published business contacts.
- Keep sends slow (start ~20–40/day) to protect deliverability.
- Honor every unsubscribe (the system does this automatically once wired up).
- To manually block someone: `python -m fixgenie.cli unsubscribe --email x@y.com`

This is not legal advice — when in doubt, check with a lawyer familiar with
anti-spam law.

---

## 10. Folder map

```
FixGenie Email Outreach Automation/
├── HOW_IT_WORKS.md          ← you are here
├── README.md                ← quick reference
├── requirements.txt         ← Python dependencies
├── .env.example             ← copy to .env and fill in secrets
├── config/
│   └── campaigns.yaml        ← WHO you target + the email sequence
├── data/
│   └── US_RealEstate_Logistics_Leads.xlsx   ← your imported leads
├── templates/               ← the 3 email templates (edit these freely)
├── src/fixgenie/            ← the engine (import, discover, enrich, validate, send)
├── n8n/                     ← no-code workflow versions
├── scripts/                 ← webhook service for auto-sending
├── docs/
│   ├── GOOGLE_SHEETS_SETUP.md
│   ├── COMPLIANCE_CHECKLIST.md
│   └── DESIGN.md             ← deep technical explanation
└── tests/                   ← automated tests
```

---

## 11. Quick troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `outreach` sends nothing | No leads have a **Valid** email yet | Run `enrich` + `validate`; check `status`. On your data, only ~37 are even crawlable. |
| "Spreadsheet not found" | Sheet not shared with service account | Share it (Editor) with the `client_email` in `service_account.json`. |
| "Sender not configured" | Missing email credentials | Fill `GMAIL_APP_PASSWORD` (or `BREVO_API_KEY`) in `.env`, or use `--dry-run`. |
| Emails landing in spam | Sending too fast / cold domain | Lower `DAILY_SEND_LIMIT`, warm up the domain gradually. |
| Import parsed 0 leads | Wrong sheet / header names | Use `--sheet "Leads"`; the importer needs a Business/Company Name column. |

---

*Start with `--dry-run` every time you touch a new batch. Preview first, send second.*
