"""
The Lead data model - the single record that flows through every stage.

Maps 1:1 to the Google Sheet schema (Section 3 of the requirements doc) plus
the auto-email tracking fields (Section 22). Keeping one model end-to-end means
discovery, enrichment, validation, storage and outreach all speak the same
language.
"""
from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


class OutreachStatus(str, Enum):
    """Allowed values for the Outreach Status column (Section 3, col N)."""

    NOT_CONTACTED = "Not Contacted"
    SENT = "Sent"
    OPENED = "Opened"
    REPLIED = "Replied"
    BOUNCED = "Bounced"
    UNSUBSCRIBED = "Unsubscribed"
    SEND_FAILED = "Send Failed"


class EmailStatus(str, Enum):
    """Allowed values for the Email Verification Status column (Section 3, col M)."""

    VALID = "Valid"
    RISKY = "Risky"
    INVALID = "Invalid"
    UNKNOWN = "Unknown"


# Column order for the Google Sheet, exactly matching Section 3 (A-P) then the
# Section 22 additions (Q-U). storage/sheets.py uses this to build the header row.
SHEET_COLUMNS: list[str] = [
    "Lead ID",                    # A
    "Date Added",                 # B
    "Business Name",              # C
    "Contact/Owner Name",         # D
    "Category/Industry",          # E
    "Email",                      # F
    "Phone",                      # G
    "Website",                    # H
    "Address",                    # I
    "City/Region",                # J
    "Source",                     # K
    "Source URL",                 # L
    "Email Verification Status",  # M
    "Outreach Status",            # N
    "Last Contacted Date",        # O
    "Notes",                      # P
    # --- Section 22 auto-email additions ---
    "Auto Email Sent",            # Q
    "Auto Email Sent At",         # R
    "Send Attempts",              # S
    "Send Error",                 # T
    "Template Version",           # U
    "Sequence Step",              # V  (which cadence step was last sent)
    "Pitch Hook",                 # W  (opener for step 1)
    "Pitch Hook 2",               # X  (opener for step 2 follow-up)
    "Pitch Hook 3",               # Y  (opener for step 3 breakup)
]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass
class Lead:
    """One business lead. Fields default to empty so partial records flow safely."""

    # --- Core identity ---
    business_name: str = ""
    contact_name: str = ""
    category: str = ""
    email: str = ""
    phone: str = ""
    website: str = ""
    address: str = ""
    city_region: str = ""

    # --- Provenance ---
    source: str = ""          # e.g. "OpenStreetMap", "Google Places", "YellowPages"
    source_url: str = ""

    # --- Status ---
    email_status: str = EmailStatus.UNKNOWN.value
    outreach_status: str = OutreachStatus.NOT_CONTACTED.value
    last_contacted_date: str = ""
    notes: str = ""

    # --- Personalization ---
    # Ready-to-use OPENER sentences in the sender's voice (set by the personalize
    # step, one per sequence step). Each becomes the first line of that email.
    # Empty is fine - templates fall back to a clean generic opener.
    pitch_hook: str = ""    # step 1 (intro)
    pitch_hook2: str = ""   # step 2 (follow-up)
    pitch_hook3: str = ""   # step 3 (breakup)
    # raw_snippet = raw descriptive text scraped from the business's own site.
    # Material for the personalize step; NOT written to the sheet, NOT put in an
    # email directly (it's in the business's voice, so it reads wrong verbatim).
    raw_snippet: str = ""

    # --- IDs / timestamps ---
    lead_id: str = ""
    date_added: str = field(default_factory=_now_iso)

    # --- Section 22: auto-email tracking ---
    auto_email_sent: bool = False
    auto_email_sent_at: str = ""
    send_attempts: int = 0
    send_error: str = ""
    template_version: str = ""
    sequence_step: int = 0

    def __post_init__(self) -> None:
        if not self.lead_id:
            self.lead_id = self.compute_id()

    # ------------------------------------------------------------------ #
    # Identity / de-dup helpers
    # ------------------------------------------------------------------ #
    def compute_id(self) -> str:
        """
        Deterministic ID from the most stable identifying fields.

        Using a hash of normalized name+city+phone means the SAME business
        rediscovered later produces the SAME id, which is the first line of
        defense against duplicates (exact-match layer; fuzzy layer is separate).
        """
        basis = "|".join(
            [
                self.business_name.strip().lower(),
                self.city_region.strip().lower(),
                _digits(self.phone),
            ]
        )
        return "FG-" + hashlib.sha1(basis.encode("utf-8")).hexdigest()[:12]

    @property
    def domain(self) -> str:
        """
        Registrable domain from the website, for enrichment + dedup.

        Prefers tldextract (handles multi-part TLDs like .co.uk precisely). Falls
        back to a urllib-based parse if tldextract is unavailable (it needs a
        network fetch on first use, which can fail in locked-down environments).
        """
        if not self.website:
            return ""
        try:
            import tldextract

            ext = tldextract.extract(self.website)
            dom = ".".join(p for p in (ext.domain, ext.suffix) if p)
            if dom:
                return dom
        except Exception:
            pass
        return _domain_fallback(self.website)

    @property
    def contact_first_name(self) -> str:
        """First token of the contact name, for template personalization."""
        return self.contact_name.split()[0] if self.contact_name else "there"

    # ------------------------------------------------------------------ #
    # Serialization
    # ------------------------------------------------------------------ #
    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_sheet_row(self) -> list[str]:
        """Render as a row in SHEET_COLUMNS order (all strings for gspread)."""
        mapping = {
            "Lead ID": self.lead_id,
            "Date Added": self.date_added,
            "Business Name": self.business_name,
            "Contact/Owner Name": self.contact_name,
            "Category/Industry": self.category,
            "Email": self.email,
            "Phone": self.phone,
            "Website": self.website,
            "Address": self.address,
            "City/Region": self.city_region,
            "Source": self.source,
            "Source URL": self.source_url,
            "Email Verification Status": self.email_status,
            "Outreach Status": self.outreach_status,
            "Last Contacted Date": self.last_contacted_date,
            "Notes": self.notes,
            "Auto Email Sent": "TRUE" if self.auto_email_sent else "FALSE",
            "Auto Email Sent At": self.auto_email_sent_at,
            "Send Attempts": str(self.send_attempts),
            "Send Error": self.send_error,
            "Template Version": self.template_version,
            "Sequence Step": str(self.sequence_step),
            "Pitch Hook": self.pitch_hook,
            "Pitch Hook 2": self.pitch_hook2,
            "Pitch Hook 3": self.pitch_hook3,
        }
        return [str(mapping.get(col, "")) for col in SHEET_COLUMNS]

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Lead":
        """Build a Lead from a dict, ignoring unknown keys."""
        known = {f for f in cls.__dataclass_fields__}  # type: ignore[attr-defined]
        return cls(**{k: v for k, v in d.items() if k in known})


def _digits(s: str) -> str:
    """Keep only digits - used for phone-based identity."""
    return "".join(ch for ch in s if ch.isdigit())


import re as _re

# Leading contact/navigation words (English + common Spanish) to strip.
_NAME_PREFIX_RE = _re.compile(
    r"^\s*(contact us|contact|home|welcome to|offices?|office|get in touch|"
    r"about us|about|learn more about|learn more|ponte en contacto con nosotros|"
    r"contacto|contactenos|contáctenos)\s*[-–—:|]*\s*",
    _re.I,
)
# Marketing/nav phrases: cut the name at the FIRST one, keep the text before it.
_NAME_MARKETING_CUT_RE = _re.compile(
    r"(?i)\b(is ready to help|overview|directions|official (?:site|website)|"
    r"address\b|call (?:us|now)|get in touch|home page)\b",
)
# A segment that is generic or a marketing tagline -> drop it, use the next.
_NAME_GENERIC_FULL_RE = _re.compile(
    r"(?i)^(home|contact|contact us|office|offices|welcome|menu|the team|team|"
    r"(leading|best|top|your|the best|#1|premier|trusted).*|.*\bagent[s]? in\b.*)$"
)


def clean_business_name(raw: str) -> str:
    """
    Tidy a scraped page title into something usable as a business name.

    Strips 'Contact'/'Home'/Spanish contact prefixes, cuts marketing tails
    ("... is ready to help you!"), drops nav segments, de-duplicates a repeated
    phrase ("Acme Inc. Acme Inc." -> "Acme Inc."), and takes the first real
    segment (brand names lead). Not perfect for run-together domain names, but
    it removes the obvious "this was scraped" tells.
    """
    if not raw:
        return ""
    name = _NAME_PREFIX_RE.sub("", raw).strip(" -–—:|,")
    # Cut at the first marketing/nav phrase.
    name = _NAME_MARKETING_CUT_RE.split(name)[0].strip(" -–—:|,&")
    # Split into segments; brands usually come first.
    segs = [s.strip(" -–—:|,&") for s in _re.split(r"\s[|–—]\s|\s-\s|\|", name)]
    segs = [s for s in segs if s and not _NAME_GENERIC_FULL_RE.match(s)]
    if segs:
        name = segs[0]
    # Collapse a phrase repeated back-to-back ("Cervera Inc. Cervera Inc.").
    name = _re.sub(r"\b(.{4,40}?)\b[\s.,]+\1\b", r"\1", name, flags=_re.I)
    name = _re.sub(r"\s+", " ", name).strip(" -–—|,.!\"'")
    return name[:80] or raw.strip()[:80]


# Two-part public suffixes common in our target regions (US/CA/UK/AU). Enough to
# extract a registrable domain correctly without a network-backed suffix list.
_TWO_PART_SUFFIXES = {
    "co.uk", "org.uk", "gov.uk", "ac.uk", "co.nz", "com.au", "net.au", "org.au",
    "co.in", "gc.ca", "on.ca", "bc.ca", "ab.ca", "qc.ca",
}


def _domain_fallback(website: str) -> str:
    """Registrable-domain extraction using only the stdlib."""
    from urllib.parse import urlparse

    w = website.strip()
    if "//" not in w:
        w = "https://" + w
    host = (urlparse(w).hostname or "").lower()
    if host.startswith("www."):
        host = host[4:]
    parts = host.split(".")
    if len(parts) <= 2:
        return host
    last_two = ".".join(parts[-2:])
    last_three = ".".join(parts[-3:])
    if last_two in _TWO_PART_SUFFIXES:
        return last_three
    return last_two
