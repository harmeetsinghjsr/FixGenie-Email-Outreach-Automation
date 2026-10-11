"""
Bulk lead finder: run the Exa finder across many (industry, city) targets and
stage everything into the local DB in one go. Then personalize -> validate ->
push, and let the daily runner email them ~DAILY_SEND_LIMIT/day.

We're global, so we DON'T hammer the same cities every day (that just returns
leads we already have). Instead we keep one big worldwide pool of
(industry, city) targets and each run searches a DIFFERENT rotating slice of it,
cycling through the whole world over time -> fresh leads every day.

Usage:
    python scripts/bulk_find.py                 # today's rotating slice
    python scripts/bulk_find.py --num 8         # results per query per target
    python scripts/bulk_find.py --count 20      # how many targets this run
    python scripts/bulk_find.py --random        # random slice instead of by-date
    python scripts/bulk_find.py --all           # search the ENTIRE pool (slow)

Edit CITY_POOL / INDUSTRIES below to change who/where you go after.
"""
from __future__ import annotations

import argparse
import random
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from exa_leads import find_leads  # noqa: E402

from fixgenie.common.config import settings  # noqa: E402
from fixgenie.storage.staging_db import StagingDB  # noqa: E402

# Local service businesses that publish an email and carry a lot of manual
# admin = good FixGenie fits. These stay constant; only the CITY changes.
INDUSTRIES = [
    "real estate",
    "law firm",
    "dental clinic",
    "marketing agency",
    "accounting firm",
    "med spa",
    "property management",
    "insurance agency",
    "roofing company",
    "hvac company",
]

# Worldwide pool of (city, region, country). English-language business markets
# where cold email is normal and deliverability is good. We rotate through all
# of these over time so we're never re-searching the same place two days running.
CITY_POOL = [
    # --- USA ---
    ("Miami", "Florida", "USA"),
    ("San Diego", "California", "USA"),
    ("Los Angeles", "California", "USA"),
    ("Chicago", "Illinois", "USA"),
    ("New York", "New York", "USA"),
    ("Dallas", "Texas", "USA"),
    ("Houston", "Texas", "USA"),
    ("Austin", "Texas", "USA"),
    ("Denver", "Colorado", "USA"),
    ("Phoenix", "Arizona", "USA"),
    ("Scottsdale", "Arizona", "USA"),
    ("Atlanta", "Georgia", "USA"),
    ("Charlotte", "North Carolina", "USA"),
    ("Seattle", "Washington", "USA"),
    ("Boston", "Massachusetts", "USA"),
    ("Nashville", "Tennessee", "USA"),
    ("Tampa", "Florida", "USA"),
    ("Orlando", "Florida", "USA"),
    ("Las Vegas", "Nevada", "USA"),
    ("Minneapolis", "Minnesota", "USA"),
    # --- Canada ---
    ("Toronto", "Ontario", "Canada"),
    ("Vancouver", "British Columbia", "Canada"),
    ("Calgary", "Alberta", "Canada"),
    ("Ottawa", "Ontario", "Canada"),
    # --- UK & Ireland ---
    ("London", "England", "United Kingdom"),
    ("Manchester", "England", "United Kingdom"),
    ("Birmingham", "England", "United Kingdom"),
    ("Leeds", "England", "United Kingdom"),
    ("Glasgow", "Scotland", "United Kingdom"),
    ("Edinburgh", "Scotland", "United Kingdom"),
    ("Bristol", "England", "United Kingdom"),
    ("Dublin", "Leinster", "Ireland"),
    # --- Australia & New Zealand ---
    ("Sydney", "New South Wales", "Australia"),
    ("Melbourne", "Victoria", "Australia"),
    ("Brisbane", "Queensland", "Australia"),
    ("Perth", "Western Australia", "Australia"),
    ("Auckland", "Auckland", "New Zealand"),
    # --- Middle East & Asia (English-business hubs) ---
    ("Dubai", "Dubai", "United Arab Emirates"),
    ("Abu Dhabi", "Abu Dhabi", "United Arab Emirates"),
    ("Singapore", "Singapore", "Singapore"),
]

# Full worldwide target list: every industry in every city. City is the OUTER
# loop so each daily slice lands on a few fresh cities (across all industries)
# rather than one industry smeared over the planet.
TARGET_POOL = [
    (industry, city, region, country)
    for (city, region, country) in CITY_POOL
    for industry in INDUSTRIES
]

# How many targets to search in one run by default. ~14 keeps a run quick while
# the rotation guarantees they're different cities than yesterday.
DEFAULT_COUNT = 14

# Fixed reference date for the by-date rotation (any stable past date works).
_ROTATE_EPOCH = date(2026, 1, 1)


def todays_targets(count: int, use_random: bool = False) -> list[tuple[str, str, str, str]]:
    """
    Pick this run's slice of TARGET_POOL.

    By default the slice advances by `count` each calendar day, marching through
    the whole pool and wrapping around - so consecutive days hit different cities
    and the entire world is covered over time. With use_random=True we instead
    take a random slice (handy for ad-hoc runs). Either way it wraps, so count
    larger than the pool just repeats the pool.
    """
    pool = TARGET_POOL
    n = len(pool)
    if n == 0:
        return []
    if use_random:
        start = random.randrange(n)
    else:
        days = (date.today() - _ROTATE_EPOCH).days
        start = (days * count) % n
    return [pool[(start + i) % n] for i in range(min(count, n))]



def main() -> None:
    ap = argparse.ArgumentParser(description="Find leads across many targets at once.")
    ap.add_argument("--num", type=int, default=8, help="results per query per target")
    ap.add_argument("--count", type=int, default=DEFAULT_COUNT,
                    help="how many (industry, city) targets to search this run")
    ap.add_argument("--random", action="store_true", dest="use_random",
                    help="pick a random slice instead of today's by-date slice")
    ap.add_argument("--all", action="store_true",
                    help="search the ENTIRE worldwide pool (slow)")
    args = ap.parse_args()

    settings.ensure_dirs()
    db = StagingDB(settings.staging_db_path)

    if args.all:
        targets = TARGET_POOL
    else:
        targets = todays_targets(args.count, use_random=args.use_random)

    picked = "random slice" if args.use_random else "today's slice"
    print(f"Searching {len(targets)} of {len(TARGET_POOL)} worldwide targets "
          f"({'full pool' if args.all else picked}).")

    total_new = total_email = 0
    for i, (industry, city, region, country) in enumerate(targets, 1):
        print(f"\n[{i}/{len(targets)}] {industry} in {city}, {region}, {country}")
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
