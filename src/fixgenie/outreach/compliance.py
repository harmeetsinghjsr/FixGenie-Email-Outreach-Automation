"""
Compliance helpers - the guardrails that keep outreach legal (Section 6).

Every commercial email MUST (CAN-SPAM / CASL):
  - identify the sender (name + company),
  - include a real physical postal address,
  - include a working, one-click unsubscribe,
  - honor opt-outs promptly.

This module provides:
  - a required legal footer (text + HTML),
  - a per-recipient unsubscribe link,
  - a persistent suppression list so we NEVER email someone who opted out.

The suppression list is a plain text file (one email per line) so it's trivial
to inspect, back up, and edit by hand. Section 13 asks for exactly this kind of
auditable opt-out process.
"""
from __future__ import annotations

import hashlib
from pathlib import Path
from urllib.parse import parse_qsl, quote, urlencode, urlsplit, urlunsplit

from fixgenie.common.logging_setup import get_logger

log = get_logger(__name__)


class SuppressionList:
    """Persistent set of emails that must never be contacted."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._entries: set[str] = set()
        self._load()

    def _load(self) -> None:
        if self.path.exists():
            for line in self.path.read_text(encoding="utf-8").splitlines():
                e = line.strip().lower()
                if e and not e.startswith("#"):
                    self._entries.add(e)

    def contains(self, email: str) -> bool:
        return email.strip().lower() in self._entries

    def add(self, email: str, reason: str = "unsubscribe") -> None:
        e = email.strip().lower()
        if not e or e in self._entries:
            return
        self._entries.add(e)
        with open(self.path, "a", encoding="utf-8") as fh:
            fh.write(f"{e}  # {reason}\n")
        log.info("Added %s to suppression list (%s).", e, reason)

    def __len__(self) -> int:
        return len(self._entries)


def unsubscribe_link(base_url: str, email: str) -> str:
    """
    Build a per-recipient unsubscribe URL with a lightweight token.

    The token lets your unsubscribe endpoint verify the request maps to a real
    send without exposing the raw email in a guessable way. (The endpoint itself
    is out of scope here - it lives on fixgenie.co - but the link is required in
    every email regardless.)
    """
    token = hashlib.sha256(email.strip().lower().encode()).hexdigest()[:16]
    return f"{base_url}?e={quote(email)}&t={token}"


def legal_footer_text(
    sender_name: str,
    sender_company: str,
    postal_address: str,
    unsubscribe_url: str,
) -> str:
    """Plain-text legal footer appended to every email."""
    return (
        f"\n\n--\n{sender_name}\n{sender_company}\n{postal_address}\n\n"
        f"You received this one-time message because your business is publicly listed "
        f"and we thought FixGenie could help. If you'd rather not hear from us, "
        f"unsubscribe here: {unsubscribe_url}\n"
    )


def personalized_booking_url(base_url: str, lead) -> str:
    """
    Turn the ONE campaign booking link into a per-lead link.

    We keep a single scheduling page (your availability lives there) but append
    query params so each lead's link is unique and useful:
      - name / email  -> pre-fill the booking form, so the recipient confirms a
        slot in ~1 click instead of retyping their details. Calendly and Cal.com
        both read `name` and `email`; Google's native Appointment schedule does
        NOT pre-fill (it just ignores them), which is why per-lead needs Calendly
        or Cal.com.
      - utm_* + lead id -> so the booking notification / your scheduling tool can
        tell you WHICH lead booked.

    Returns "" when base_url is unset (button hidden).
    """
    if not base_url:
        return ""
    extra = {
        "name": (lead.contact_name or lead.business_name or "").strip(),
        "email": (lead.email or "").strip(),
        "utm_source": "fixgenie",
        "utm_medium": "email",
        "utm_content": (lead.lead_id or "").strip(),
    }
    extra = {k: v for k, v in extra.items() if v}
    parts = urlsplit(base_url)
    merged = dict(parse_qsl(parts.query))
    merged.update(extra)
    return urlunsplit(
        (parts.scheme, parts.netloc, parts.path, urlencode(merged), parts.fragment)
    )


def booking_button_html(url: str, cta: str) -> str:
    """
    A single, email-client-safe "book a call" block (inline styles only - Gmail
    and Outlook strip <style> blocks). Sits above the legal footer. A short
    lead-in and sub-line make it read like an instant, no-hassle booking.
    """
    if not url:
        return ""
    label = cta or "Book a call"
    return (
        '<div style="margin:28px 0;text-align:center;'
        'font-family:Arial,Helvetica,sans-serif">'
        '<p style="margin:0 0 12px;font-size:14px;color:#444">'
        'Rather skip the back-and-forth? Grab a time that works for you:</p>'
        f'<a href="{url}" '
        'style="background:#2563eb;color:#ffffff;text-decoration:none;'
        'font-weight:700;font-size:16px;padding:14px 32px;border-radius:8px;'
        'display:inline-block">'
        f'\U0001F4C5 {label}</a>'
        '<p style="margin:10px 0 0;font-size:12px;color:#888">'
        "Pick any open slot &mdash; you'll get an instant calendar invite "
        'with a video link.</p>'
        '</div>'
    )


def booking_line_text(url: str, cta: str) -> str:
    """Plain-text equivalent of the booking block (for the text/plain part)."""
    if not url:
        return ""
    label = cta or "Book a call"
    return (
        f"\n\nRather skip the back-and-forth? {label} - pick any open slot and "
        f"you'll get an instant calendar invite with a video link:\n{url}\n"
    )


def legal_footer_html(
    sender_name: str,
    sender_company: str,
    postal_address: str,
    unsubscribe_url: str,
) -> str:
    """HTML legal footer (kept minimal - heavy HTML hurts deliverability, Section 21)."""
    return (
        '<hr style="border:none;border-top:1px solid #ddd;margin:24px 0 12px">'
        f'<p style="font-size:12px;color:#888;line-height:1.5">'
        f"{sender_name}<br>{sender_company}<br>{postal_address}<br><br>"
        "You received this one-time message because your business is publicly "
        "listed and we thought FixGenie could help. "
        f'If you\'d rather not hear from us, <a href="{unsubscribe_url}">unsubscribe here</a>.'
        "</p>"
    )
