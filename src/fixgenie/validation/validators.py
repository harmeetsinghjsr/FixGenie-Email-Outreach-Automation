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

from typing import Callable, Iterable

from fixgenie.common.logging_setup import get_logger
from fixgenie.common.models import EmailStatus, Lead

log = get_logger(__name__)

_ROLE_PREFIXES = {
    "info", "contact", "hello", "sales", "support", "admin", "office",
    "enquiries", "inquiries", "team", "help", "service", "bookings", "no-reply",
    "noreply",
}

# Cache conclusive MX lookups per domain within a run to avoid repeat DNS
# queries. Inconclusive ones (network down) are never cached.
_mx_cache: dict[str, bool] = {}

# A domain that always has MX records. If even this can't be resolved, the
# problem is our network/resolver, not the lead's domain.
_CONTROL_DOMAIN = "gmail.com"
_control_checked_at = 0.0
_control_ok = False


def _resolver_healthy() -> bool:
    """True if DNS works right now (checked at most every 30s)."""
    global _control_checked_at, _control_ok
    import time

    now = time.monotonic()
    if now - _control_checked_at < 30:
        return _control_ok
    try:
        import dns.resolver

        _control_ok = len(dns.resolver.resolve(_CONTROL_DOMAIN, "MX", lifetime=8)) > 0
    except Exception:
        _control_ok = False
    _control_checked_at = now
    return _control_ok


def _has_mx(domain: str, attempts: int = 3) -> bool | None:
    """
    True  - the domain has MX records.
    False - it definitely has none (NXDOMAIN / no MX answer, with DNS healthy).
    None  - couldn't tell: the lookup failed, or DNS itself is down.

    Treating "couldn't tell" as "no mail server" once marked a whole run's
    leads Invalid during a DNS outage, silently excluding them from outreach.
    """
    if domain in _mx_cache:
        return _mx_cache[domain]
    import time

    import dns.resolver

    delay = 2.0
    for attempt in range(1, attempts + 1):
        try:
            ok = len(dns.resolver.resolve(domain, "MX", lifetime=8)) > 0
            _mx_cache[domain] = ok
            return ok
        except (dns.resolver.NXDOMAIN, dns.resolver.NoAnswer):
            # Definitive only if the resolver is answering correctly: some
            # VPN/hotspot setups report NXDOMAIN for everything while offline.
            if _resolver_healthy():
                _mx_cache[domain] = False
                return False
        except Exception:  # timeout, no nameservers, network down
            pass
        if attempt < attempts:
            time.sleep(delay)
            delay *= 2
    return None


def validate_email(lead: Lead, require_mx: bool = True, role_is_risky: bool = True) -> bool:
    """
    Set lead.email and lead.email_status in place.

    Returns False if the result is inconclusive because the MX lookup could
    not be completed (network/DNS failure); the lead should be re-validated
    later rather than stored. Returns True otherwise.
    """
    if not lead.email:
        lead.email_status = EmailStatus.UNKNOWN.value
        return True

    from email_validator import EmailNotValidError, validate_email as _ve

    try:
        # check_deliverability=False here; we do our own MX check below so we
        # control the Valid/Risky nuance.
        result = _ve(lead.email, check_deliverability=False)
        normalized = result.normalized.lower()
    except EmailNotValidError as exc:
        log.info("Invalid email '%s': %s", lead.email, exc)
        lead.email_status = EmailStatus.INVALID.value
        return True

    lead.email = normalized
    domain = normalized.split("@", 1)[1]
    prefix = normalized.split("@", 1)[0].split("+")[0]

    # MX check.
    if require_mx:
        has_mx = _has_mx(domain)
        if has_mx is None:
            lead.email_status = EmailStatus.UNKNOWN.value
            return False
        if not has_mx:
            lead.email_status = EmailStatus.INVALID.value
            lead.notes = _note(lead, "no MX record for domain")
            return True

    # Role-email downgrade.
    if role_is_risky and prefix in _ROLE_PREFIXES:
        lead.email_status = EmailStatus.RISKY.value
        lead.notes = _note(lead, "role-based email (CASL: treat with care)")
        return True

    lead.email_status = EmailStatus.VALID.value
    return True


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
    on_lead: Callable[[Lead], None] | None = None,
) -> list[Lead]:
    """
    Batch validate: email + phone for each lead.

    `on_lead` is called with each lead as soon as it is validated, so the
    pipeline can persist progress incrementally (MX lookups hit DNS and can be
    slow over a large batch).

    Leads whose MX lookup was inconclusive (DNS/network down) are left out of
    the result and never passed to `on_lead`, so they stay where they were and
    get validated again on the next run instead of being stored as Invalid.
    """
    out: list[Lead] = []
    deferred = 0
    for lead in leads:
        if not validate_email(lead, require_mx=require_mx, role_is_risky=role_is_risky):
            deferred += 1
            continue
        validate_phone(lead, default_region=default_region)
        out.append(lead)
        if on_lead:
            on_lead(lead)
    if deferred:
        log.warning(
            "%d leads not validated: MX lookups failed (DNS/network down). "
            "They stay queued and will be validated on the next run.", deferred,
        )
    return out
