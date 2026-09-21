"""
Import already-scraped leads from an Excel (.xlsx) file into the staging DB.

Built for the FixGenie "US_RealEstate_Logistics_Leads.xlsx" layout, but the
column mapping is data-driven (see COLUMN_ALIASES) so it tolerates minor header
differences and multiple sheets.

Key behavior for THIS dataset: the Email column contains placeholders like
"Not public - website contact form" rather than real addresses. Those are NOT
emails, so we store them as an empty email + leave a note. The enrichment stage
(website crawler) then tries to find a real address from each business website.
That's the whole reason email lives downstream of import here.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Iterable

from fixgenie.common.logging_setup import get_logger
from fixgenie.common.models import EmailStatus, Lead

log = get_logger(__name__)

_EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}")

# Header text (lowercased) -> Lead field. Multiple aliases map to one field so
# the importer works across the different sheets in the workbook.
COLUMN_ALIASES: dict[str, str] = {
    "business name": "business_name",
    "company name": "business_name",
    "owner / key contact": "contact_name",
    "owner/key contact": "contact_name",
    "owner": "contact_name",
    "industry": "category",
    "email": "email",
    "phone": "phone",
    "website": "website",
    "city, state": "city_region",
    "state": "city_region",
    "linkedin": "linkedin",     # captured into notes/source_url
    "notes / verify on call": "notes",
    "notes": "notes",
    "description": "notes",
}

# Phrases that mean "no real email here" -> treat as empty.
_NOT_AN_EMAIL = ("not public", "contact form", "n/a", "none", "verify", "-")


def _clean_email(raw: object) -> str:
    val = str(raw or "").strip()
    if not val:
        return ""
    low = val.lower()
    if any(p in low for p in _NOT_AN_EMAIL) and not _EMAIL_RE.search(val):
        return ""
    m = _EMAIL_RE.search(val)
    return m.group(0).lower() if m else ""


def _clean_website(raw: object) -> str:
    val = str(raw or "").strip()
    if not val or "not confirmed" in val.lower() or "verify" in val.lower():
        # keep only if it still looks like a domain
        if not re.search(r"\.[a-z]{2,}", val.lower()):
            return ""
    # Strip stray text, keep the domain-ish token.
    m = re.search(r"([a-zA-Z0-9\-]+\.)+[a-zA-Z]{2,}(/\S*)?", val)
    return m.group(0) if m else ""


def _map_row(header: list[str], row: tuple, sheet_name: str) -> Lead | None:
    """Turn one spreadsheet row into a Lead using COLUMN_ALIASES."""
    fields: dict[str, str] = {}
    extra_notes: list[str] = []
    linkedin = ""

    for col_name, value in zip(header, row):
        key = str(col_name or "").strip().lower()
        target = COLUMN_ALIASES.get(key)
        if not target:
            continue
        if target == "linkedin":
            linkedin = str(value or "").strip()
            continue
        if target == "email":
            fields["email"] = _clean_email(value)
        elif target == "website":
            fields["website"] = _clean_website(value)
        elif target == "notes":
            v = str(value or "").strip()
            if v:
                extra_notes.append(v)
        else:
            fields[target] = str(value or "").strip()

    business_name = fields.get("business_name", "").strip()
    if not business_name:
        return None  # skip blank / summary rows

    notes = "; ".join(extra_notes)
    if linkedin:
        notes = (notes + "; " if notes else "") + f"LinkedIn: {linkedin}"

    lead = Lead(
        business_name=business_name,
        contact_name=fields.get("contact_name", ""),
        category=fields.get("category", ""),
        email=fields.get("email", ""),
        phone=fields.get("phone", ""),
        website=fields.get("website", ""),
        city_region=fields.get("city_region", ""),
        source=f"Excel import ({sheet_name})",
        source_url=linkedin,
        notes=notes,
        email_status=EmailStatus.UNKNOWN.value,
    )
    return lead


def read_leads_from_excel(
    path: Path,
    sheets: Iterable[str] | None = None,
    skip_sheets: Iterable[str] = ("Summary", "Call Tracker"),
) -> list[Lead]:
    """
    Read leads from the workbook.

    - `sheets`: if given, only read these tabs. Otherwise read all tabs except
      `skip_sheets` (Summary is a dashboard, Call Tracker duplicates Leads).
    - De-dups within the file by the Lead's deterministic id.
    """
    import openpyxl

    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    targets = list(sheets) if sheets else [s for s in wb.sheetnames if s not in set(skip_sheets)]

    seen: set[str] = set()
    leads: list[Lead] = []
    for sheet_name in targets:
        if sheet_name not in wb.sheetnames:
            log.warning("Sheet '%s' not found; skipping.", sheet_name)
            continue
        ws = wb[sheet_name]
        rows = list(ws.iter_rows(values_only=True))
        if not rows:
            continue
        header = [str(c or "").strip() for c in rows[0]]
        # A valid lead sheet must have a business/company name column.
        if not any(h.lower() in ("business name", "company name") for h in header):
            log.info("Sheet '%s' has no business-name column; skipping.", sheet_name)
            continue
        for row in rows[1:]:
            lead = _map_row(header, row, sheet_name)
            if lead is None:
                continue
            if lead.lead_id in seen:
                continue
            seen.add(lead.lead_id)
            leads.append(lead)
        log.info("Read %d leads from sheet '%s'.", len(leads), sheet_name)

    log.info("Excel import: %d unique leads total from %s.", len(leads), path.name)
    return leads


def import_excel_to_staging(path: Path, db, sheets: Iterable[str] | None = None) -> int:
    """Read the workbook and upsert every lead into the staging DB (stage='new')."""
    leads = read_leads_from_excel(path, sheets=sheets)
    added = 0
    for lead in leads:
        if db.upsert(lead, stage="new"):
            added += 1
    log.info("Imported %d new leads into staging (of %d read).", added, len(leads))
    return added
