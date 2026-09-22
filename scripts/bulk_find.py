"""
Bulk lead finder: run the Exa finder across many (industry, city) targets and
stage everything into the local DB in one go. Then personalize -> validate ->
push, and let the daily runner email them ~DAILY_SEND_LIMIT/day.

Usage:
    python scripts/bulk_find.py                 # use the default TARGETS below
    python scripts/bulk_find.py --num 8         # results per query per target

Edit TARGETS to change who you go after.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from exa_leads import find_leads  # noqa: E402

from fixgenie.common.config import settings  # noqa: E402
from fixgenie.storage.staging_db import StagingDB  # noqa: E402

# (industry, city, region, country). Local service businesses that publish an
# email and carry a lot of manual admin = good FixGenie fits.
TARGETS = [
    ("real estate", "Miami", "Florida", "USA"),
    ("real estate", "San Diego", "California", "USA"),
    ("law firm", "Chicago", "Illinois", "USA"),
    ("law firm", "Toronto", "Ontario", "Canada"),
    ("dental clinic", "Denver", "Colorado", "USA"),
    ("dental clinic", "Vancouver", "British Columbia", "Canada"),
    ("marketing agency", "Toronto", "Ontario", "Canada"),
    ("marketing agency", "New York", "New York", "USA"),
    ("accounting firm", "Dallas", "Texas", "USA"),
    ("med spa", "Scottsdale", "Arizona", "USA"),
    ("property management", "Atlanta", "Georgia", "USA"),
    ("insurance agency", "Charlotte", "North Carolina", "USA"),
    ("roofing company", "Houston", "Texas", "USA"),
    ("hvac company", "Phoenix", "Arizona", "USA"),
]


def main() -> None:
    ap = argparse.ArgumentParser(description="Find leads across many targets at once.")
    ap.add_argument("--num", type=int, default=8, help="results per query per target")
    args = ap.parse_args()

    settings.ensure_dirs()
    db = StagingDB(settings.staging_db_path)

    total_new = total_email = 0
    for i, (industry, city, region, country) in enumerate(TARGETS, 1):
        print(f"\n[{i}/{len(TARGETS)}] {industry} in {city}, {region}")
        try:
            leads = find_leads(industry, city, region, country, args.num)
        except Exception as exc:  # noqa: BLE001
            print(f"  ! target failed: {type(exc).__name__}: {str(exc)[:80]}")
            continue
        new = sum(1 for lead in leads if db.upsert(lead, stage="new"))
        with_email = sum(1 for lead in leads if lead.email)
        total_new += new
        total_email += with_email
        print(f"  staged {new} new ({with_email} with email)")

    print(f"\n==== DONE: {total_new} new leads staged, {total_email} have an email. ====")
    print("Next: python scripts/personalize.py  ->  validate  ->  push")


if __name__ == "__main__":
    main()
