"""
ONE-TIME cleaner: remove leads that can't be emailed and haven't been contacted.

"Important field missing" = no email address, so the lead can never be
outreached. To stay safe, this ONLY removes a row when ALL of these are true:
  * Email is blank, AND
  * it has NOT been sent (Auto Email Sent is not TRUE), AND
  * Outreach Status is still "Not Contacted".

Anything already emailed, or with a real address, is left untouched.

Run on YOUR PC:
    python scripts/clean_rows.py --dry-run     # show what WOULD be removed
    python scripts/clean_rows.py               # actually remove them
"""
from __future__ import annotations

import argparse
import time

from fixgenie.common.config import settings
from fixgenie.storage.sheets import SheetsClient


def _should_remove(lead) -> bool:
    contacted = lead.auto_email_sent or (lead.outreach_status or "").strip().lower() not in ("", "not contacted")
    return (not lead.email) and (not contacted)


def _contiguous_ranges(rows: list[int]) -> list[tuple[int, int]]:
    """Group sorted row numbers into (start, end) inclusive contiguous ranges."""
    ranges: list[tuple[int, int]] = []
    for r in sorted(rows):
        if ranges and r == ranges[-1][1] + 1:
            ranges[-1] = (ranges[-1][0], r)
        else:
            ranges.append((r, r))
    return ranges


def main() -> None:
    ap = argparse.ArgumentParser(description="Remove un-emailable, not-yet-contacted leads from the sheet.")
    ap.add_argument("--dry-run", action="store_true", help="Show what would be removed; delete nothing.")
    args = ap.parse_args()

    client = SheetsClient(
        settings.resolve_path(settings.google_service_account_json),
        settings.google_sheet_name,
    )
    leads = client.load_all()  # also builds client._id_to_row (lead_id -> 1-based row)

    to_remove = [l for l in leads if _should_remove(l)]
    rows = [client._id_to_row[l.lead_id] for l in to_remove if l.lead_id in (client._id_to_row or {})]

    print(f"{len(leads)} leads total; {len(to_remove)} have no email and were never contacted"
          f"{' (dry run)' if args.dry_run else ''}.")
    for l in to_remove:
        print(f"  - {l.business_name[:40]:40} | {l.category or '(no category)'} | {l.city_region}")

    if not rows:
        return
    if args.dry_run:
        print("\nDry run: nothing deleted.")
        return

    # Delete from the bottom up so earlier row numbers stay valid, and group
    # contiguous rows into single delete calls to stay under the API quota.
    ranges = _contiguous_ranges(rows)
    for start, end in sorted(ranges, reverse=True):
        client._leads_ws.delete_rows(start, end)
        time.sleep(1.2)  # be gentle with the Sheets write quota
    print(f"\nRemoved {len(rows)} rows. {len(leads) - len(rows)} leads remain.")


if __name__ == "__main__":
    main()
