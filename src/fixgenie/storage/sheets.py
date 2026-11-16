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

import time
from pathlib import Path
from typing import Any, Callable, TypeVar

from fixgenie.common.logging_setup import get_logger
from fixgenie.common.models import SHEET_COLUMNS, Lead

log = get_logger(__name__)

T = TypeVar("T")

# Network blips (DNS drops, resets) and transient Google errors are common on
# flaky links and must never kill an otherwise-successful run.
_RETRY_ATTEMPTS = 4
_RETRY_BASE_DELAY = 2.0  # seconds; doubles each attempt -> 2, 4, 8

# Permanent configuration errors: never retry, surface them immediately.
_PERMANENT_ERRORS = (FileNotFoundError, PermissionError, IsADirectoryError, NotADirectoryError)

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


def _is_transient(exc: Exception) -> bool:
    """True if this error is a momentary network/API blip worth retrying."""
    import socket

    # DNS failures arrive wrapped in all sorts of transport exception types, so
    # walk the __cause__/__context__ chain looking for the underlying socket error.
    seen: set[int] = set()
    cur: BaseException | None = exc
    while cur is not None and id(cur) not in seen:
        seen.add(id(cur))
        # Checked before OSError: FileNotFoundError/PermissionError subclass it,
        # but "spreadsheet not shared with the service account" is a permanent,
        # actionable misconfiguration - retrying it just delays the real message.
        if isinstance(cur, _PERMANENT_ERRORS):
            return False
        if isinstance(cur, (socket.gaierror, ConnectionError, TimeoutError, OSError)):
            return True
        cur = cur.__cause__ or cur.__context__

    name = type(exc).__name__
    if name in ("TransportError", "ServerNotFoundError", "ConnectionError"):
        return True

    # google-api-core / gspread HTTP errors: retry 429 + 5xx only.
    status = getattr(getattr(exc, "response", None), "status_code", None)
    if isinstance(status, int):
        return status == 429 or status >= 500

    return False


def _with_retry(label: str, fn: Callable[[], T]) -> T:
    """Run `fn`, retrying transient network errors with exponential backoff."""
    delay = _RETRY_BASE_DELAY
    for attempt in range(1, _RETRY_ATTEMPTS + 1):
        try:
            return fn()
        except Exception as exc:  # noqa: BLE001 - re-raised unless classified transient
            if attempt == _RETRY_ATTEMPTS or not _is_transient(exc):
                raise
            log.warning(
                "%s failed (attempt %d/%d): %s - retrying in %.0fs",
                label, attempt, _RETRY_ATTEMPTS, exc, delay,
            )
            time.sleep(delay)
            delay *= 2
    raise AssertionError("unreachable")


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
        gc = _with_retry("authorize", lambda: gspread.authorize(creds))
        # Publish connection state only once the whole handshake succeeded: if
        # _open_or_create() blows up halfway, the next call must reconnect
        # rather than sail on with a half-built client (self._leads_ws is None).
        self._gc = gc
        try:
            # Wraps opening the spreadsheet AND reading each tab's header row -
            # all of those hit the network. A missing/unshared file raises
            # FileNotFoundError, which _is_transient treats as permanent.
            _with_retry("open workbook", self._open_or_create)
        except Exception:
            self._gc = self._spreadsheet = self._leads_ws = self._log_ws = None
            raise

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
        records = _with_retry(
            "load leads", self._leads_ws.get_all_records
        )  # list of dicts keyed by header
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
        _with_retry(
            "append lead",
            lambda: self._leads_ws.append_row(lead.to_sheet_row(), value_input_option="RAW"),
        )
        if self._id_to_row is not None:
            # Row index is (existing rows + 1). Cheaper to just invalidate cache.
            self._id_to_row = None

    def append_leads_bulk(self, leads: list[Lead]) -> int:
        """Append many rows in ONE API call (quota-friendly). Returns count."""
        if not leads:
            return 0
        self.connect()
        rows = [lead.to_sheet_row() for lead in leads]
        _with_retry(
            "append leads",
            lambda: self._leads_ws.append_rows(rows, value_input_option="RAW"),
        )
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
        _with_retry(
            "update lead",
            lambda: self._leads_ws.update(
                [lead.to_sheet_row()], f"A{row}:{end_col}{row}", value_input_option="RAW"
            ),
        )
        return True

    def log_event(self, lead: Lead, event: str, detail: str = "") -> None:
        """Append one row to the Outreach Log tab (audit trail, Section 13)."""
        from datetime import datetime, timezone

        self.connect()
        row = [
            datetime.now(timezone.utc).isoformat(timespec="seconds"),
            lead.lead_id,
            lead.business_name,
            lead.email,
            event,
            detail,
        ]
        _with_retry(
            "log event",
            lambda: self._log_ws.append_row(row, value_input_option="RAW"),
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
