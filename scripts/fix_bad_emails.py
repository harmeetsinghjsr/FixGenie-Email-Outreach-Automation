"""
ONE-TIME fixer: clean URL-encoded email addresses that slipped into the data.

Some Exa-scraped emails came back URL-encoded (e.g. "%20info@domain.com" from a
mailto: link, or "nata%6c%69e.n%61...@domain.com"). The fix in exa_leads.py
now prevents NEW occurrences, but these already exist in the DB and the sheet.

This script:
  * Finds leads with "%" in their email (in staging DB AND Google Sheet)
  * Decodes the URL-encoding, validates the result, and writes it back
  * Re-runs MX + role-email validation on the cleaned address
  * Updates the Google Sheet row in place

Run on YOUR PC (needs Google Sheets access):
    python scripts/fix_bad_emails.py              # fix all
    python scripts/fix_bad_emails.py --dry-run    # show what would change
"""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
from urllib.parse import unquote

from fixgenie.common.config import settings
from fixgenie.common.models import Lead, EmailStatus
from fixgenie.storage.sheets import SheetsClient
from fixgenie.validation.validators import validate_email

_EMAIL_CLEAN_RE = re.compile(r"[a-z0-9._%+-]+@[a-z0-9.-]+\.[a-z]{2,}")


def _clean_email(raw: str) -> str:
    """Decode URL-encoded email and return only the clean address, or '' if invalid."""
    decoded = unquote(raw).strip().lower()
    m = _EMAIL_CLEAN_RE.fullmatch(decoded)
    if m:
        return m.group(0)
    return ""


def main() -> None:
    ap = argparse.ArgumentParser(description="Fix URL-encoded email addresses.")
    ap.add_argument("--dry-run", action="store_true", help="Show what would change; write nothing.")
    args = ap.parse_args()

    # --- Fix in staging DB ---
    print("=== Staging DB ===")
    conn = sqlite3.connect(settings.staging_db_path)
    rows = conn.execute("SELECT lead_id, stage, data FROM leads").fetchall()
    bad_count = 0
    for lead_id, stage, data_json in rows:
        data = json.loads(data_json)
        raw_email = data.get("email", "")
        if "%" in raw_email:
            cleaned = _clean_email(raw_email)
            if cleaned:
                print(f"  {lead_id} ({stage}): {raw_email!r} -> {cleaned!r}")
                data["email"] = cleaned
                data["email_status"] = EmailStatus.UNKNOWN.value  # will re-validate
                bad_count += 1
                if not args.dry_run:
                    conn.execute(
                        "UPDATE leads SET data=? WHERE lead_id=?",
                        (json.dumps(data), lead_id),
                    )
            else:
                print(f"  {lead_id} ({stage}): {raw_email!r} -> UNRECOVERABLE (skipping)")
    if not args.dry_run:
        conn.commit()
    conn.close()
    print(f"  Fixed {bad_count} leads in staging DB{' (dry run)' if args.dry_run else ''}")

    # --- Fix in Google Sheet ---
    print("\n=== Google Sheet ===")
    client = SheetsClient(
        settings.resolve_path(settings.google_service_account_json),
        settings.google_sheet_name,
    )
    all_leads = client.load_all()
    sheet_bad = [l for l in all_leads if l.email and "%" in l.email]
    print(f"  Found {len(sheet_bad)} leads with encoded emails in sheet")

    ok = 0
    for lead in sheet_bad:
        cleaned = _clean_email(lead.email)
        if cleaned:
            print(f"  {lead.lead_id}: {lead.email!r} -> {cleaned!r}")
            lead.email = cleaned
            lead.email_status = EmailStatus.UNKNOWN.value
            # Re-validate the cleaned email
            validate_email(lead)
            ok += 1
            if not args.dry_run:
                client.update_lead(lead)
        else:
            print(f"  {lead.lead_id}: {lead.email!r} -> UNRECOVERABLE (skipping)")
    print(f"\n  Fixed {ok} leads in Google Sheet{' (dry run)' if args.dry_run else ''}")


if __name__ == "__main__":
    main()
