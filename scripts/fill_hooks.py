"""
ONE-TIME fixer: fill in missing AI pitch hooks directly in the Google Sheet.

Some leads (e.g. ones the cloud run added while its LLM step was blocked) landed
in the sheet with an email but BLANK Pitch Hook columns (W/X/Y). Those leads only
exist in the sheet, not in your local database, so scripts/personalize.py can't
see them. This script talks to the sheet directly:

  * read every lead,
  * for each one that has an email but is missing any of the 3 hooks,
  * ask your LLM for opener/followup/breakup,
  * write them straight back into that row.

Run it on YOUR PC (the LLM gateway works here, not on GitHub):

    python scripts/fill_hooks.py                 # fill everything missing
    python scripts/fill_hooks.py --limit 20      # just the first 20 (test run)
    python scripts/fill_hooks.py --dry-run       # show what WOULD change, write nothing
"""
from __future__ import annotations

import argparse
import sys
import time

from fixgenie.common.config import settings
from fixgenie.storage.sheets import SheetsClient

# Reuse the exact same LLM call the normal personalize step uses.
from personalize import _call_llm  # type: ignore


def _needs_hooks(lead) -> bool:
    return bool(lead.email) and not (lead.pitch_hook and lead.pitch_hook2 and lead.pitch_hook3)


def main() -> None:
    ap = argparse.ArgumentParser(description="Fill missing AI pitch hooks directly in the Google Sheet.")
    ap.add_argument("--limit", type=int, default=None, help="Only process the first N that need hooks.")
    ap.add_argument("--delay", type=float, default=0.4, help="Seconds between LLM calls.")
    ap.add_argument("--dry-run", action="store_true", help="Show what would change; write nothing.")
    args = ap.parse_args()

    if not settings.has_llm:
        sys.exit("LLM not configured. Set LLM_BASE_URL + LLM_API_KEY in .env.")

    client = SheetsClient(
        settings.resolve_path(settings.google_service_account_json),
        settings.google_sheet_name,
    )
    leads = client.load_all()
    todo = [l for l in leads if _needs_hooks(l)]
    if args.limit:
        todo = todo[: args.limit]

    print(f"{len(leads)} leads total; {len(todo)} need AI hooks"
          f"{' (dry run)' if args.dry_run else ''}.")
    if not todo:
        return

    ok = fail = 0
    for i, lead in enumerate(todo, 1):
        city = lead.city_region.split(",")[0].strip() if lead.city_region else ""
        try:
            result = None
            for attempt in range(3):
                try:
                    result = _call_llm(lead.business_name, lead.category, city,
                                       lead.website, lead.raw_snippet)
                    break
                except Exception:  # noqa: BLE001 - retry empty/garbled replies
                    if attempt == 2:
                        raise
                    time.sleep(1.0)
            company = str(result.get("company_name", "")).strip()
            if company:
                lead.business_name = company[:80]
            if result.get("opener"):
                lead.pitch_hook = str(result["opener"]).strip()[:220]
            if result.get("followup"):
                lead.pitch_hook2 = str(result["followup"]).strip()[:220]
            if result.get("breakup"):
                lead.pitch_hook3 = str(result["breakup"]).strip()[:220]

            if args.dry_run:
                print(f"  [{i}/{len(todo)}] would fill {lead.business_name[:30]:30} | {(lead.pitch_hook or '')[:60]}")
            else:
                client.update_lead(lead)
                print(f"  [{i}/{len(todo)}] {lead.business_name[:30]:30} | {(lead.pitch_hook or '')[:60]}")
            ok += 1
        except Exception as exc:  # noqa: BLE001 - keep going on a single bad lead
            fail += 1
            print(f"  [{i}/{len(todo)}] failed: {type(exc).__name__}: {str(exc)[:80]}")
        time.sleep(args.delay)

    print(f"\nFilled {ok} leads ({fail} failed).")


if __name__ == "__main__":
    main()
