"""
Unit tests for the pure-logic pieces (no network, no API keys needed).
Run with:  pytest
"""
from __future__ import annotations

import sys
from pathlib import Path

# Make src/ importable without installing.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from fixgenie.common.models import EmailStatus, Lead, OutreachStatus, SHEET_COLUMNS  # noqa: E402
from fixgenie.storage.dedup import filter_new_leads, is_duplicate  # noqa: E402


# --------------------------------------------------------------------------- #
# Lead model
# --------------------------------------------------------------------------- #
def test_lead_id_is_deterministic():
    a = Lead(business_name="Joe's Plumbing", city_region="Toronto, ON", phone="+14165551234")
    b = Lead(business_name="Joe's Plumbing", city_region="Toronto, ON", phone="+14165551234")
    assert a.lead_id == b.lead_id
    assert a.lead_id.startswith("FG-")


def test_lead_id_differs_for_different_business():
    a = Lead(business_name="Joe's Plumbing", city_region="Toronto, ON")
    b = Lead(business_name="Sam's Salon", city_region="Toronto, ON")
    assert a.lead_id != b.lead_id


def test_sheet_row_length_matches_columns():
    lead = Lead(business_name="Test Co", email="a@b.com")
    row = lead.to_sheet_row()
    assert len(row) == len(SHEET_COLUMNS)
    assert all(isinstance(cell, str) for cell in row)


def test_contact_first_name_falls_back():
    assert Lead().contact_first_name == "there"
    assert Lead(contact_name="Jane Doe").contact_first_name == "Jane"


def test_domain_extraction():
    lead = Lead(website="https://www.example.co.uk/contact")
    assert lead.domain == "example.co.uk"


def test_roundtrip_dict():
    lead = Lead(business_name="X", email="x@y.com", send_attempts=2)
    clone = Lead.from_dict(lead.to_dict())
    assert clone.business_name == "X"
    assert clone.send_attempts == 2


# --------------------------------------------------------------------------- #
# De-duplication
# --------------------------------------------------------------------------- #
def test_duplicate_by_fuzzy_name_same_city():
    a = Lead(business_name="Joe's Plumbing", city_region="Toronto, ON")
    b = Lead(business_name="Joes Plumbing Inc", city_region="Toronto, ON")
    assert is_duplicate(a, b) is True


def test_duplicate_by_shared_phone():
    a = Lead(business_name="Totally Different Name", phone="+1 (416) 555-1234")
    b = Lead(business_name="Another Name", phone="+14165551234")
    assert is_duplicate(a, b) is True


def test_not_duplicate_different_business():
    a = Lead(business_name="Joe's Plumbing", city_region="Toronto, ON")
    b = Lead(business_name="Elite Roofing", city_region="Toronto, ON")
    assert is_duplicate(a, b) is False


def test_filter_new_leads_drops_internal_dupes():
    candidates = [
        Lead(business_name="Joe's Plumbing", city_region="Toronto, ON"),
        Lead(business_name="Joes Plumbing", city_region="Toronto, ON"),  # dup of #1
        Lead(business_name="Sam Salon", city_region="Austin, TX"),
    ]
    new, dropped = filter_new_leads(candidates, existing=[])
    assert len(new) == 2
    assert dropped == 1


def test_filter_new_leads_respects_existing():
    existing = [Lead(business_name="Joe's Plumbing", city_region="Toronto, ON")]
    candidates = [Lead(business_name="Joes Plumbing Inc", city_region="Toronto, ON")]
    new, dropped = filter_new_leads(candidates, existing=existing)
    assert len(new) == 0
    assert dropped == 1


def test_drop_known_leads_skips_sheet_rows_before_personalizing(tmp_path):
    from fixgenie.pipeline import drop_known_leads
    from fixgenie.storage.staging_db import StagingDB

    db = StagingDB(tmp_path / "staging.db")
    known = Lead(business_name="Joes Plumbing Inc", city_region="Toronto, ON")
    fresh = Lead(business_name="Elite Roofing", city_region="Toronto, ON")
    # Two different businesses sharing a junk scraped name must both survive:
    # only Sheet rows are compared, never the batch against itself.
    junk_a = Lead(business_name="Contact Us", city_region="Austin, TX", phone="+15125550001")
    junk_b = Lead(business_name="Contact Us", city_region="Austin, TX", phone="+15125550002")
    for lead in (known, fresh, junk_a, junk_b):
        db.upsert(lead, stage="new")

    sheet = [Lead(business_name="Joe's Plumbing", city_region="Toronto, ON")]
    assert drop_known_leads(db, sheet) == 1

    remaining = {l.lead_id for l in db.get_by_stage("new")}
    assert remaining == {fresh.lead_id, junk_a.lead_id, junk_b.lead_id}
    assert [l.lead_id for l in db.get_by_stage("duplicate")] == [known.lead_id]


def test_drop_known_leads_noop_without_sheet_rows(tmp_path):
    from fixgenie.pipeline import drop_known_leads
    from fixgenie.storage.staging_db import StagingDB

    db = StagingDB(tmp_path / "staging.db")
    db.upsert(Lead(business_name="Elite Roofing", city_region="Toronto, ON"), stage="new")
    assert drop_known_leads(db, []) == 0
    assert len(db.get_by_stage("new")) == 1


# --------------------------------------------------------------------------- #
# Enums
# --------------------------------------------------------------------------- #
def test_status_enum_values():
    assert OutreachStatus.NOT_CONTACTED.value == "Not Contacted"
    assert EmailStatus.VALID.value == "Valid"
