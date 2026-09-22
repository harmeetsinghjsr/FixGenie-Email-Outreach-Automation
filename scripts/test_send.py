"""
One-off test send - renders a real sequence step EXACTLY as outreach would and
emails it to a single address, WITHOUT touching the Google Sheet.

Use it to confirm end-to-end sending works and to see the booking button in a
real inbox. It builds a throwaway in-memory Lead, so nothing is logged/persisted.

Usage:
    python scripts/test_send.py --to hs978698@gmail.com
    python scripts/test_send.py --to you@example.com --step 2

The booking button only appears if BOOKING_URL is set (in .env, or inline:
    BOOKING_URL="https://calendly.com/you/15min" python scripts/test_send.py --to ...)
"""
from __future__ import annotations

import argparse

from fixgenie.common.config import settings
from fixgenie.common.models import EmailStatus, Lead
from fixgenie.outreach.engine import OutreachEngine
from fixgenie.outreach.senders import build_sender


def main() -> None:
    ap = argparse.ArgumentParser(description="Send one test email through the real pipeline.")
    ap.add_argument("--to", required=True, help="Destination email address.")
    ap.add_argument("--step", type=int, default=1, help="Sequence step to render (default 1).")
    args = ap.parse_args()

    sender = build_sender(settings)
    if not sender.is_configured():
        raise SystemExit(
            f"Email sender '{settings.email_provider}' is not configured - "
            "check EMAIL_PROVIDER and the matching keys in .env."
        )

    seq = OutreachEngine.sequence_from_config(settings.campaigns)
    step = next((s for s in seq if s.step == args.step), None)
    if step is None:
        raise SystemExit(f"No step {args.step} in the configured sequence.")

    engine = OutreachEngine(sender, settings.templates_dir, seq, settings, dry_run=False)

    lead = Lead(
        business_name="Acme Plumbing",
        contact_name="Harmeet",
        category="plumber",
        city_region="Cambridge, Ontario",
        email=args.to,
        email_status=EmailStatus.VALID.value,
        pitch_hook=(
            "Most plumbers I talk to still handle booking and follow-ups by hand - "
            "a little automation there quietly gives back hours every week."
        ),
    )

    subject, text_body, html_body = engine.render(lead, step)
    ok, detail = sender.send(lead.email, lead.contact_name, subject, text_body, html_body)

    print(f"{'SENT' if ok else 'FAILED'}: {detail}")
    print(f"  provider : {settings.email_provider}")
    print(f"  from     : {settings.sender_name} <{settings.sender_email}>")
    print(f"  to       : {args.to}")
    print(f"  step     : {step.step}  ({step.template})")
    print(f"  subject  : {subject}")
    print(f"  booking  : {'ON' if settings.has_booking else 'OFF (BOOKING_URL unset)'}")
    if not ok:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
