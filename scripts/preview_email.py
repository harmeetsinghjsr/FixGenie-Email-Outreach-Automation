"""
Preview the outreach emails locally - no Google Sheets, no SMTP, no sending.

Renders the configured sequence exactly as the sender would: same OutreachEngine,
same Jinja templates, same legal footer. That matters - because the preview goes
through the real render path, it can't drift from what actually goes on the wire.

Nothing here touches the network or your Sheet. It is purely a look at the copy.

Usage:
    python scripts/preview_email.py                  # every step, sample lead
    python scripts/preview_email.py --step 2         # just step 2
    python scripts/preview_email.py --name Dana --business "Acme Plumbing"
    python scripts/preview_email.py --html           # also print the HTML part
"""
from __future__ import annotations

import sys
from pathlib import Path

# Allow running as a plain script whether or not the package is pip-installed.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

import click  # noqa: E402

from fixgenie.common.config import settings  # noqa: E402
from fixgenie.common.models import EmailStatus, Lead, OutreachStatus  # noqa: E402
from fixgenie.outreach.engine import OutreachEngine  # noqa: E402

# Windows consoles default to a legacy codepage (cp1252), which turns the em
# dashes in the templates into mojibake on screen. The emails themselves are
# sent as UTF-8 either way (see senders.py) - this is purely so the preview is
# faithful to read. Force UTF-8 output if the interpreter supports it.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

# The value shipped in .env.example - almost certainly not a real address.
_PLACEHOLDER_MARKER = "123 Example St"


def _sample_lead(name: str, business: str, category: str, city: str, email: str) -> Lead:
    """A stand-in lead so the templates have something to personalize against."""
    return Lead(
        business_name=business,
        contact_name=name,
        category=category,
        email=email,
        city_region=city,
        email_status=EmailStatus.VALID.value,
        outreach_status=OutreachStatus.NOT_CONTACTED.value,
        sequence_step=0,
    )


@click.command()
@click.option("--step", type=int, default=None, help="Only preview this sequence step.")
@click.option("--name", default="Dana", help="Sample contact name (drives the greeting).")
@click.option("--business", default="Acme Plumbing", help="Sample business name.")
@click.option("--category", default="plumber", help="Sample category (appears in the copy).")
@click.option("--city", default="Toronto, Ontario", help="Sample city/region.")
@click.option("--email", default="owner@example.com", help="Sample recipient address.")
@click.option("--html", "show_html", is_flag=True, help="Also print the HTML part.")
def main(
    step: int | None,
    name: str,
    business: str,
    category: str,
    city: str,
    email: str,
    show_html: bool,
) -> None:
    """Print each outreach email exactly as it would be sent."""
    engine = OutreachEngine(
        sender=None,  # type: ignore[arg-type]  # render() never touches the sender
        templates_dir=settings.templates_dir,
        sequence=OutreachEngine.sequence_from_config(settings.campaigns),
        settings=settings,
        dry_run=True,
    )
    lead = _sample_lead(name, business, category, city, email)

    steps = [s for s in engine.sequence if step is None or s.step == step]
    if not steps:
        raise SystemExit(
            f"No step {step} in the sequence defined in config/campaigns.yaml."
        )

    print(f"Sending as : {settings.sender_name} <{settings.sender_email}>")
    print(f"Provider   : {settings.email_provider}")
    print(f"Recipient  : {lead.contact_name} <{lead.email}>")

    if _PLACEHOLDER_MARKER in settings.sender_postal_address:
        print()
        print("!! SENDER_POSTAL_ADDRESS is still the placeholder from .env.example.")
        print("   That exact string is stamped into every footer. Set a real address")
        print("   in .env before sending anything.")

    for s in steps:
        subject, text_body, html_body = engine.render(lead, s)
        print()
        print("=" * 72)
        print(f"STEP {s.step}   (wait_days={s.wait_days}, template={s.template})")
        print("=" * 72)
        print(f"Subject: {subject}")
        print("-" * 72)
        print(text_body)
        if show_html:
            print("-" * 72)
            print("HTML part:")
            print(html_body)
    print()


if __name__ == "__main__":
    main()
