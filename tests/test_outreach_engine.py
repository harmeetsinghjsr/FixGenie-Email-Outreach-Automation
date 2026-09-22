"""
Tests for the outreach engine's send-decision logic + template rendering,
using a fake sender so nothing actually goes out.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from fixgenie.common.models import EmailStatus, Lead, OutreachStatus  # noqa: E402
from fixgenie.outreach.engine import OutreachEngine, SequenceStep  # noqa: E402
from fixgenie.outreach.senders import EmailSender  # noqa: E402

TEMPLATES = Path(__file__).resolve().parents[1] / "templates"


class FakeSettings:
    sender_name = "Harmeet Singh"
    sender_company = "FixGenie Consulting Inc"
    sender_email = "hello@fixgenie.co"
    sender_postal_address = "123 Example St, Toronto, ON"
    unsubscribe_base_url = "https://fixgenie.co/unsubscribe"
    booking_url = ""
    booking_cta = "Book a 15-min call"
    daily_send_limit = 40
    send_delay_seconds = 0
    suppression_path = Path("/tmp/fixgenie_test_suppression.txt")


class FakeSender(EmailSender):
    def __init__(self):
        self.sent = []

    def is_configured(self):
        return True

    def send(self, to_email, to_name, subject, text_body, html_body):
        self.sent.append((to_email, subject, text_body))
        return True, "fake-message-id"


def _engine(sender, dry_run=False):
    # Clean suppression file between tests.
    if FakeSettings.suppression_path.exists():
        FakeSettings.suppression_path.unlink()
    seq = [
        SequenceStep(1, 0, "email_1_intro.j2", "Quick idea for {{ business_name }}"),
        SequenceStep(2, 3, "email_2_value.j2", "Re: Quick idea for {{ business_name }}"),
    ]
    return OutreachEngine(sender, TEMPLATES, seq, FakeSettings(), dry_run=dry_run)


def test_sends_to_valid_not_contacted_lead():
    sender = FakeSender()
    engine = _engine(sender)
    lead = Lead(
        business_name="Joe's Plumbing",
        contact_name="Joe Smith",
        email="joe@joesplumbing.com",
        email_status=EmailStatus.VALID.value,
        city_region="Toronto, ON",
    )
    persisted = []
    result = engine.run([lead], persist=lambda l: persisted.append(l))

    assert result.sent == 1
    assert len(sender.sent) == 1
    to_email, subject, body = sender.sent[0]
    assert to_email == "joe@joesplumbing.com"
    assert "Joe's Plumbing" in subject
    assert "Joe" in body                       # personalized greeting
    assert "unsubscribe" in body.lower()       # compliance footer present
    assert "123 Example St" in body            # postal address present
    assert lead.outreach_status == OutreachStatus.SENT.value
    assert lead.sequence_step == 1
    assert lead.auto_email_sent is True


def test_skips_invalid_email():
    sender = FakeSender()
    engine = _engine(sender)
    lead = Lead(business_name="X", email="x@x.com", email_status=EmailStatus.INVALID.value)
    result = engine.run([lead], persist=lambda l: None)
    assert result.sent == 0
    assert result.skipped == 1


def test_skips_already_replied():
    sender = FakeSender()
    engine = _engine(sender)
    lead = Lead(
        business_name="X",
        email="x@x.com",
        email_status=EmailStatus.VALID.value,
        outreach_status=OutreachStatus.REPLIED.value,
    )
    result = engine.run([lead], persist=lambda l: None)
    assert result.sent == 0


def test_suppression_blocks_send():
    sender = FakeSender()
    engine = _engine(sender)
    engine.suppression.add("blocked@x.com", reason="test")
    lead = Lead(business_name="X", email="blocked@x.com", email_status=EmailStatus.VALID.value)
    result = engine.run([lead], persist=lambda l: None)
    assert result.sent == 0
    assert result.skipped == 1


def test_dry_run_does_not_send():
    sender = FakeSender()
    engine = _engine(sender, dry_run=True)
    lead = Lead(business_name="X", email="x@x.com", email_status=EmailStatus.VALID.value)
    result = engine.run([lead], persist=lambda l: None)
    assert result.sent == 1          # counted as "would send"
    assert len(sender.sent) == 0     # but nothing actually sent
    assert lead.outreach_status == OutreachStatus.NOT_CONTACTED.value  # unchanged


def test_daily_cap_enforced():
    sender = FakeSender()
    engine = _engine(sender)
    engine.settings.daily_send_limit = 2
    leads = [
        Lead(business_name=f"Biz {i}", email=f"b{i}@x.com", email_status=EmailStatus.VALID.value)
        for i in range(5)
    ]
    result = engine.run(leads, persist=lambda l: None)
    assert result.sent == 2
