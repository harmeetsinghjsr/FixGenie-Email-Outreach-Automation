"""
Progress tracker: a one-glance dashboard of your whole campaign.

Reads the Google Sheet and prints, in plain English:
  * how many leads you have and how many are actually emailable,
  * where they are in the 3-email sequence (not contacted / sent / replied / ...),
  * how many have their AI pitch hooks filled,
  * what's ready to go out on your next send.

It only READS the sheet - it never changes or sends anything, so it's always
safe to run.

Run on YOUR PC:
    python scripts/progress.py
"""
from __future__ import annotations

from collections import Counter

from fixgenie.common.config import settings
from fixgenie.storage.sheets import SheetsClient


def _bar(count: int, total: int, width: int = 24) -> str:
    """A tiny text progress bar, e.g. [#########---------------] 38%."""
    if total <= 0:
        return "[" + "-" * width + "]   0%"
    filled = round(width * count / total)
    pct = round(100 * count / total)
    return "[" + "#" * filled + "-" * (width - filled) + f"] {pct:3d}%"


def _line(label: str, count: int, total: int) -> str:
    return f"  {label:22} {count:4d}  {_bar(count, total)}"


def main() -> None:
    client = SheetsClient(
        settings.resolve_path(settings.google_service_account_json),
        settings.google_sheet_name,
    )
    leads = client.load_all()
    total = len(leads)

    if total == 0:
        print("No leads in the sheet yet. Run scripts/run_all.bat to find some.")
        return

    emailable = [l for l in leads if l.email]
    valid = [l for l in emailable if (l.email_status or "").strip().lower() == "valid"]
    hooks_done = [l for l in emailable if l.pitch_hook and l.pitch_hook2 and l.pitch_hook3]

    email_status = Counter((l.email_status or "Unknown").strip() or "Unknown" for l in leads)
    outreach = Counter((l.outreach_status or "Not Contacted").strip() or "Not Contacted" for l in leads)

    sent = sum(1 for l in leads if l.auto_email_sent)
    ready = [l for l in valid if not l.auto_email_sent
             and (l.outreach_status or "").strip().lower() in ("", "not contacted")]

    print("=" * 60)
    print(f"  FixGenie campaign progress  ({settings.google_sheet_name})")
    print("=" * 60)

    print(f"\nLEADS: {total} total")
    print(_line("have an email", len(emailable), total))
    print(_line("email = Valid", len(valid), total))
    print(_line("AI hooks filled in", len(hooks_done), total))

    print("\nEMAIL QUALITY:")
    for status in ("Valid", "Risky", "Invalid", "Unknown"):
        if email_status.get(status):
            print(_line(status, email_status[status], total))

    print("\nOUTREACH FUNNEL:")
    for status in ("Not Contacted", "Sent", "Opened", "Replied",
                   "Bounced", "Unsubscribed", "Send Failed"):
        if outreach.get(status):
            print(_line(status, outreach[status], total))

    print("\nAT A GLANCE:")
    print(f"  Emails sent so far ....... {sent}")
    print(f"  Ready to send next ....... {len(ready)}  (Valid + not yet contacted)")
    print(f"  Daily send limit ......... {settings.daily_send_limit}")
    if ready:
        runs = -(-len(ready) // max(settings.daily_send_limit, 1))  # ceil
        print(f"  -> at {settings.daily_send_limit}/day, first emails clear in ~{runs} run(s).")
    print()


if __name__ == "__main__":
    main()
