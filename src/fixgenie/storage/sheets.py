"""
Google Sheets client (the "CRM" layer).

Uses a service account + gspread. The Sheet has two tabs:
  - "Leads"        : one row per lead, schema from models.SHEET_COLUMNS
  - "Outreach Log" : append-only event log (every send/open/bounce), Section 10

Design notes:
  - We read the whole Leads tab once and cache it, so dedup + status updates
    don't make one API call per row (Sheets quota is ~60 reads/min).
  - Every write is idempotent on Lead ID: append if new, update the matching
    row if it exists.
  - If credentials are missing we raise a clear, actionable error rather than a
    cryptic google-auth stack trace.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from fixgenie.common.logging_setup import get_logger
from fixgenie.common.models import SHEET_COLUMNS, Lead

log = get_logger(__name__)

# Full drive scope is required so gspread can open a spreadsheet *by name* that
# was created by hand and shared with the service account. The narrower
# drive.file scope only exposes files the service account created itself, which
# breaks the documented "share an existing sheet" setup flow.
_SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

LEADS_TAB = "Leads"
LOG_TAB = "Outreach Log"
LOG_COLUMNS = ["Timestamp", "Lead ID", "Business Name", "Email", "Event", "Detail"]


class SheetsClient:
    def __init__(self, service_account_json: str | Path, sheet_name: str) -> None:
        self.sheet_name = sheet_name
        self._sa_path = Path(service_account_json)
        self._gc: Any = None
        self._spreadsheet: Any = None
        self._leads_ws: Any = None
        self._log_ws: Any = None
        self._id_to_row: dict[str, int] | None = None  # lead_id -> 1-based row

    # ------------------------------------------------------------------ #
    # Connection
    # ------------------------------------------------------------------ #
    def connect(self) -> None:
        if self._gc is not None:
            return
        if not self._sa_path.exists():
            raise FileNotFoundError(
                f"Google service-account file not found at '{self._sa_path}'. "
                "See docs/GOOGLE_SHEETS_SETUP.md to create one, then set "
                "GOOGLE_SERVICE_ACCOUNT_JSON in your .env."
            )
        import gspread
        from google.oauth2.service_account import Credentials

        creds = Credentials.from_service_account_file(str(self._sa_path), scopes=_SCOPES)
        self._gc = gspread.authorize(creds)
        self._open_or_create()

    def _open_or_create(self) -> None:
        import gspread

        try:
            self._spreadsheet = self._gc.open(self.sheet_name)
        except gspread.SpreadsheetNotFound:
            raise FileNotFoundError(
                f"Spreadsheet '{self.sheet_name}' not found or not shared with the "
                "service account. Create it and share it (Editor) with the "
                "client_email from your service_account.json."
            )
        self._leads_ws = self._ensure_tab(LEADS_TAB, SHEET_COLUMNS)
        self._log_ws = self._ensure_tab(LOG_TAB, LOG_COLUMNS)

    def _ensure_tab(self, title: str, header: list[str]) -> Any:
        import gspread

        try:
            ws = self._spreadsheet.worksheet(title)
        except gspread.WorksheetNotFound:
            ws = self._spreadsheet.add_worksheet(title=title, rows=1000, cols=max(26, len(header)))
            ws.update([header], "A1")
            log.info("Created worksheet tab '%s'", title)
            return ws
        # Make sure the header row matches (write it if the sheet is empty).
        existing = ws.row_values(1)
        if existing != header:
            ws.update([header], "A1")
        return ws

    # ------------------------------------------------------------------ #
    # Reads
    # ------------------------------------------------------------------ #
    def load_all(self) -> list[Lead]:
        """Read every lead row into Lead objects and build the id->row index."""
        self.connect()
        records = self._leads_ws.get_all_records()  # list of dicts keyed by header
        leads: list[Lead] = []
        self._id_to_row = {}
        for i, rec in enumerate(records, start=2):  # row 1 = header
            lead = self._record_to_lead(rec)
            leads.append(lead)
            if lead.lead_id:
                self._id_to_row[lead.lead_id] = i
        return leads

    @staticmethod
    def _record_to_lead(rec: dict[str, Any]) -> Lead:
        """Map a Sheet row (header-keyed dict) back into a Lead."""
        return Lead.from_dict(
            {
                "lead_id": str(rec.get("Lead ID", "")),
                "date_added": str(rec.get("Date Added", "")),
                "business_name": str(rec.get("Business Name", "")),
                "contact_name": str(rec.get("Contact/Owner Name", "")),
                "category": str(rec.get("Category/Industry", "")),
                "email": str(rec.get("Email", "")),
                "phone": str(rec.get("Phone", "")),
                "website": str(rec.get("Website", "")),
                "address": str(rec.get("Address", "")),
                "city_region": str(rec.get("City/Region", "")),
                "source": str(rec.get("Source", "")),
                "source_url": str(rec.get("Source URL", "")),
                "email_status": str(rec.get("Email Verification Status", "Unknown")),
                "outreach_status": str(rec.get("Outreach Status", "Not Contacted")),
                "last_contacted_date": str(rec.get("Last Contacted Date", "")),
                "notes": str(rec.get("Notes", "")),
                "auto_email_sent": str(rec.get("Auto Email Sent", "")).upper() == "TRUE",
                "auto_email_sent_at": str(rec.get("Auto Email Sent At", "")),
                "send_attempts": _safe_int(rec.get("Send Attempts", 0)),
                "send_error": str(rec.get("Send Error", "")),
                "template_version": str(rec.get("Template Version", "")),
                "sequence_step": _safe_int(rec.get("Sequence Step", 0)),
                "pitch_hook": str(rec.get("Pitch Hook", "")),
                "pitch_hook2": str(rec.get("Pitch Hook 2", "")),
                "pitch_hook3": str(rec.get("Pitch Hook 3", "")),
            }
        )

    # ------------------------------------------------------------------ #
    # Writes
    # ------------------------------------------------------------------ #
    def append_lead(self, lead: Lead) -> None:
        """Append a brand-new lead row."""
        self.connect()
        self._leads_ws.append_row(lead.to_sheet_row(), value_input_option="RAW")
        if self._id_to_row is not None:
            # Row index is (existing rows + 1). Cheaper to just invalidate cache.
            self._id_to_row = None

    def append_leads_bulk(self, leads: list[Lead]) -> int:
        """Append many rows in ONE API call (quota-friendly). Returns count."""
        if not leads:
            return 0
        self.connect()
        rows = [lead.to_sheet_row() for lead in leads]
        self._leads_ws.append_rows(rows, value_input_option="RAW")
        self._id_to_row = None
        return len(rows)

    def update_lead(self, lead: Lead) -> bool:
        """Update the existing row matching lead.lead_id. Returns False if not found."""
        self.connect()
        if self._id_to_row is None:
            self.load_all()
        row = (self._id_to_row or {}).get(lead.lead_id)
        if not row:
            return False
        # Write the full row range A:V in one update call.
        end_col = _col_letter(len(SHEET_COLUMNS))
        self._leads_ws.update([lead.to_sheet_row()], f"A{row}:{end_col}{row}",
                              value_input_option="RAW")
        return True

    def log_event(self, lead: Lead, event: str, detail: str = "") -> None:
        """Append one row to the Outreach Log tab (audit trail, Section 13)."""
        from datetime import datetime, timezone

        self.connect()
        self._log_ws.append_row(
            [
                datetime.now(timezone.utc).isoformat(timespec="seconds"),
                lead.lead_id,
                lead.business_name,
                lead.email,
                event,
                detail,
            ],
            value_input_option="RAW",
        )


def _safe_int(v: Any) -> int:
    try:
        return int(str(v).strip() or 0)
    except (ValueError, TypeError):
        return 0


def _col_letter(n: int) -> str:
    """1 -> A, 26 -> Z, 27 -> AA ..."""
    result = ""
    while n > 0:
        n, rem = divmod(n - 1, 26)
        result = chr(65 + rem) + result
    return result
