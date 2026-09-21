"""
Email + phone validation - fully free and mostly offline.

Email:
  - Syntax + normalization via `email-validator`.
  - Deliverability signal via a live MX-record DNS lookup (does the domain
    actually accept mail?). This is the free stand-in for a paid bounce checker
    like ZeroBounce - it won't catch every dead mailbox but it eliminates the
    biggest bounce source (domains with no mail server at all).
  - Role emails (info@, sales@) are flagged "Risky" per the CASL note in
    Section 6 (the role-email exemption is narrow; don't blast them).

Phone:
  - `phonenumbers` (Google's libphonenumber) validates and formats to E.164.

Sets Lead.email_status to Valid / Risky / Invalid / Unknown (Section 3, col M).
"""
from __future__ import annotations

from typing import Iterable

from fixgenie.common.logging_setup import get_logger
from fixgenie.common.models import EmailStatus, Lead

log = get_logger(__name__)

_ROLE_PREFIXES = {
    "info", "contact", "hello", "sales", "support", "admin", "office",
    "enquiries", "inquiries", "team", "help", "service", "bookings", "no-reply",
    "noreply",
}

# Cache MX lookups per domain within a run to avoid repeat DNS queries.
_mx_cache: dict[str, bool] = {}


def _has_mx(domain: str) -> bool:
    if domain in _mx_cache:
        return _mx_cache[domain]
    ok = False
    try:
        import dns.resolver

        answers = dns.resolver.resolve(domain, "MX")
        ok = len(answers) > 0
    except Exception:
        # No MX record, NXDOMAIN, or resolver error -> treat as no mail server.
        ok = False
    _mx_cache[domain] = ok
    return ok


def validate_email(lead: Lead, require_mx: bool = True, role_is_risky: bool = True) -> None:
    """Set lead.email and lead.email_status in place."""
    if not lead.email:
        lead.email_status = EmailStatus.UNKNOWN.value
        return

    from email_validator import EmailNotValidError, validate_email as _ve

    try:
        # check_deliverability=False here; we do our own MX check below so we
        # control the Valid/Risky nuance.
        result = _ve(lead.email, check_deliverability=False)
        normalized = result.normalized.lower()
    except EmailNotValidError as exc:
        log.info("Invalid email '%s': %s", lead.email, exc)
        lead.email_status = EmailStatus.INVALID.value
        return

    lead.email = normalized
    domain = normalized.split("@", 1)[1]
    prefix = normalized.split("@", 1)[0].split("+")[0]

    # MX check.
    if require_mx and not _has_mx(domain):
        lead.email_status = EmailStatus.INVALID.value
        lead.notes = _note(lead, "no MX record for domain")
        return

    # Role-email downgrade.
    if role_is_risky and prefix in _ROLE_PREFIXES:
        lead.email_status = EmailStatus.RISKY.value
        lead.notes = _note(lead, "role-based email (CASL: treat with care)")
        return

    lead.email_status = EmailStatus.VALID.value


def validate_phone(lead: Lead, default_region: str = "US") -> None:
    """Format lead.phone to E.164 in place; blank it if clearly invalid."""
    if not lead.phone:
        return
    import phonenumbers

    # Guess region from country if we have it.
    region = _region_hint(lead.city_region) or default_region
    try:
        parsed = phonenumbers.parse(lead.phone, region)
        if phonenumbers.is_valid_number(parsed):
            lead.phone = phonenumbers.format_number(
                parsed, phonenumbers.PhoneNumberFormat.E164
            )
        else:
            # Keep the raw value but note it wasn't validated.
            lead.notes = _note(lead, "phone failed validation")
    except phonenumbers.NumberParseException:
        lead.notes = _note(lead, "phone unparseable")


def _region_hint(city_region: str) -> str:
    cr = city_region.lower()
    if any(x in cr for x in ("ontario", "british columbia", "quebec", "alberta", "canada", "toronto", "vancouver")):
        return "CA"
    return ""


def _note(lead: Lead, msg: str) -> str:
    return (lead.notes + "; " if lead.notes else "") + msg


def validate_leads(
    leads: Iterable[Lead],
    require_mx: bool = True,
    role_is_risky: bool = True,
    default_region: str = "US",
) -> list[Lead]:
    """Batch validate: email + phone for each lead."""
    out: list[Lead] = []
    for lead in leads:
        validate_email(lead, require_mx=require_mx, role_is_risky=role_is_risky)
        validate_phone(lead, default_region=default_region)
        out.append(lead)
    return out
