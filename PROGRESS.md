# FixGenie — Outreach System Progress Tracker

A plain-English status board for the **whole outreach system** — what's built,
what's working, and what's intentionally off. This tracks the *system*, not the
day-to-day lead numbers (for live campaign stats run `python scripts/progress.py`).

_Last updated: 2026-09-22_

---

## Overall status: ✅ Live and running (local PC mode)

The system finds leads, writes personalized emails with AI, stores everything in
a Google Sheet, and sends a polite 3-email sequence with automatic follow-ups.
Everything runs on your PC with one command (`scripts\run_all.bat`).

---

## Components

| # | Part of the system | Status | Notes |
|---|---|---|---|
| 1 | **Lead discovery** (Exa web search) | ✅ Done | `scripts/exa_leads.py` — finds businesses + emails |
| 2 | **Bulk lead finding** | ✅ Done | `scripts/bulk_find.py` — many industries/cities at once |
| 3 | **AI personalization** | ✅ Done | clean company name + 3 tailored openers per lead |
| 4 | **Enrichment** | ✅ Done | adds owner/contact name, extra emails |
| 5 | **Email validation** | ✅ Done | Valid / Risky / Invalid / Unknown grading |
| 6 | **Google Sheet CRM** | ✅ Done | de-dup + push; the sheet is the source of truth |
| 7 | **3-email outreach sequence** | ✅ Done | intro (day 0) → follow-up (day 3) → breakup (day 7) |
| 8 | **Automatic follow-ups** | ✅ Done | sends only leads who are due |
| 9 | **Auto-stop on reply/unsub/bounce** | ✅ Done | sequence halts for anyone who responds or opts out |
| 10 | **Compliance footer** | ✅ Done | real identity, postal address, working unsubscribe link |
| 11 | **Daily send cap** | ✅ Done | `DAILY_SEND_LIMIT` (currently 30) protects sender reputation |
| 12 | **One-click runner** | ✅ Done | `scripts/run_all.bat` — find → personalize → push → send |
| 13 | **Campaign dashboard** | ✅ Done | `scripts/progress.py` — read-only live stats |
| 14 | **Sheet maintenance tools** | ✅ Done | `fill_hooks.py` (fill AI hooks), `clean_rows.py` (remove junk rows) |
| 15 | **Docs / README** | ✅ Done | full setup + command reference in `README.md` |
| 16 | **Booking button** (per-lead) | ✅ Done | one-click "book a call" in every email; per-lead Calendly/Cal.com link (pre-fills name/email, tags lead id). Set `BOOKING_URL` to switch on |
| 17 | **Test-send tool** | ✅ Done | `scripts/test_send.py` — fire one real email at yourself without touching the sheet |
| 18 | **Cloud automation** (GitHub Actions) | ⏸️ Off by design | send-only in cloud; find + AI blocked from GitHub IPs → run locally |

---

## Recently completed

- ✅ Added a **per-lead booking button** (`BOOKING_URL`/`BOOKING_CTA`): styled
  "book a call" CTA in every email, with each lead's name/email/id baked into the
  link so Calendly/Cal.com pre-fills their details and tells you who booked.
- ✅ Added `scripts/test_send.py` to send one real email to any address for
  end-to-end verification (verified live to a personal inbox via Brevo).
- ✅ Switched to **PC-only** operation via one command (`run_all.bat`); disabled
  the daily cloud cron (it couldn't find leads or personalize).
- ✅ Back-filled **AI pitch hooks** for every emailable lead (`fill_hooks.py`).
- ✅ Cleaned out **un-emailable, never-contacted junk rows** (`clean_rows.py`).
- ✅ Added a **campaign dashboard** (`progress.py`).
- ✅ Refreshed the **README** with all current commands and the local-only workflow.

---

## Intentionally off / not doing

- ⏸️ **Cloud auto-send (cron).** Left as a manual "Run workflow" button only.
  Re-enable by uncommenting the `schedule` block in
  `.github/workflows/pipeline.yml` if you ever want a cloud send.

---

## Ideas / possible next steps (not started)

- ⬜ Reply detection straight from the inbox (auto-mark "Replied" without manual check).
- ⬜ A/B test subject lines and track open/reply rates per variant.
- ⬜ Weekly summary emailed to you automatically.

---

## How to check live numbers

This file tracks the *system*. For today's actual campaign numbers (leads,
Valid emails, sent, ready-to-send), run:

```bash
python scripts/progress.py
```
