# Compliance Checklist — read before your first send

> **This is general information, not legal advice.** Anti-spam laws carry real
> penalties (CASL fines can be very large). Before sending at scale, consult a
> lawyer familiar with CAN-SPAM (US), CASL (Canada), and TCPA/CRTC (calls/SMS).
> This checklist reflects the guidance in Section 6 of the requirements pack.

---

## Before you send anything

- [ ] **Physical postal address is set** (`SENDER_POSTAL_ADDRESS` in `.env`).
      A real mailing address is legally required in every commercial email
      (CAN-SPAM). A PO box or registered business address is fine.
- [ ] **Sender identity is accurate** — `SENDER_NAME`, `SENDER_COMPANY`, and the
      From address honestly identify FixGenie. No deceptive "From" or subject lines.
- [ ] **Unsubscribe link works.** Every email includes one automatically, but the
      link points at `UNSUBSCRIBE_BASE_URL`. Make sure that page exists on
      fixgenie.co and actually records opt-outs (or forwards them to you).
- [ ] **Opt-out handling is wired up.** When someone unsubscribes, their email
      must land in `data/suppression_list.txt` (via the ESP webhook →
      `/esp/webhook`, or manually via `fixgenie unsubscribe --email ...`).
      Opt-outs must be honored within 10 business days (CAN-SPAM) — sooner is better.

---

## Data sourcing

- [ ] **Only publicly published business data.** You're collecting business
      contact info that the business itself put online for business purposes.
      Don't collect personal/private data.
- [ ] **Respect source terms.** Overpass (OpenStreetMap) is open data — fine.
      If you enable the directory scraper, confirm that site's ToS permits it and
      that `respect_robots` is left on.
- [ ] **Don't scrape Google Maps / LinkedIn / Yelp.** Their ToS forbid it and
      it's a common enforcement flashpoint. Use their official APIs instead
      (the Places source is wired for exactly this).

---

## US — CAN-SPAM (cold B2B email is allowed if…)

- [ ] Accurate header/from information.
- [ ] Non-deceptive subject lines.
- [ ] Physical postal address present.
- [ ] Clear opt-out, honored within 10 business days.
- [ ] No emailing addresses harvested in ways that violate a site's ToS.

## Canada — CASL (stricter — treat as consent-first)

- [ ] Understand that CASL generally requires **consent** (express or implied)
      before emailing. "Implied consent" includes a narrow existing-business-
      relationship window and some published role addresses — but the exemption
      is **narrow**. Do not treat it as a blanket pass.
- [ ] Every message identifies the sender and includes a working unsubscribe
      (the system does this for you).
- [ ] Consider starting outreach with **US targets** while you get CASL guidance
      for Canadian ones, given the stricter regime. (Your `campaigns.yaml`
      controls the mix.)

## Phone / SMS (if you add it later)

- [ ] **US TCPA:** automated/pre-recorded calls and texts to numbers without
      consent are restricted. Manual, individual calls to a business's published
      line are lower-risk than autodialed/blasted SMS.
- [ ] **Canada CRTC + CASL:** similar restrictions on telemarketing and
      commercial texts.
- [ ] This system does **not** send SMS by default, on purpose.

---

## Deliverability hygiene (protects you + is good practice)

- [ ] **Warm up new domains/mailboxes.** Start at ~20–40 sends/day
      (`DAILY_SEND_LIMIT`) and ramp slowly.
- [ ] **Send only to `Valid` emails** by default (`send_only_if_status_in`).
      `Risky`/role emails are stored but not sent.
- [ ] **Keep templates light.** Plain text or minimal HTML — heavy HTML hurts
      deliverability and looks like spam.
- [ ] **Test on 20–30 leads first** (`--dry-run`, then a small real batch) and
      confirm the unsubscribe flow end-to-end before scaling.

---

## Ongoing

- [ ] Review bounces/complaints regularly; suppress hard bounces.
- [ ] Keep the `Source URL` audit trail intact so any lead can be traced and
      removed on request.
- [ ] Re-verify free-tier limits and legal requirements periodically — both
      change over time.
