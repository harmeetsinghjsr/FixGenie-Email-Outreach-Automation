"""
Website enrichment crawler - free, self-built (no API cost).

Given a lead with a website, it:
  1. Fetches the homepage + a few likely contact pages (/contact, /about, ...).
  2. Extracts emails (regex), obvious owner/contact names (heuristics on
     About/Contact copy), and a phone if we don't have one yet.
  3. Prefers a personal/role email over a generic one, and records what it found
     in the Notes field for the audit trail (Section 13).

This is the "visit business website to get owner name & email" step from the
requirements. It only ever reads PUBLIC pages the business published itself,
which is the lowest-risk enrichment path (Section 6).
"""
from __future__ import annotations

import re
from typing import Callable, Iterable

import requests
from bs4 import BeautifulSoup

from fixgenie.common.logging_setup import get_logger
from fixgenie.common.models import Lead

log = get_logger(__name__)

_USER_AGENT = "FixGenie-Outreach/1.0 (contact: hello@fixgenie.co)"

# Pages most likely to carry contact details / owner names.
_CANDIDATE_PATHS = ["", "/contact", "/contact-us", "/about", "/about-us", "/team"]

_EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}")

# Emails we treat as "role" (generic) rather than a person.
_ROLE_PREFIXES = {
    "info", "contact", "hello", "sales", "support", "admin", "office",
    "enquiries", "inquiries", "team", "help", "service", "bookings",
}

# Junk emails to ignore outright (asset/library noise).
_JUNK_EMAIL_SUFFIXES = (".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".css", ".js")

# Heuristic patterns that often precede an owner's name on About/Contact pages.
_OWNER_PATTERNS = [
    re.compile(r"(?:owner|founder|proprietor|president|ceo|principal)[:\s\-]+([A-Z][a-z]+ [A-Z][a-z]+)"),
    re.compile(r"([A-Z][a-z]+ [A-Z][a-z]+)\s*[,\-]?\s*(?:owner|founder|proprietor|president|ceo)"),
    re.compile(r"(?:founded|established|started) by ([A-Z][a-z]+ [A-Z][a-z]+)"),
]


class WebsiteCrawler:
    def __init__(self, max_pages: int = 5, timeout: int = 12) -> None:
        self.max_pages = max_pages
        self.timeout = timeout
        self._session = requests.Session()
        self._session.headers.update({"User-Agent": _USER_AGENT})

    def enrich(self, lead: Lead) -> Lead:
        """Fill email/contact_name/phone gaps from the lead's website. Returns the lead."""
        if not lead.website:
            return lead
        base = self._normalize(lead.website)
        if not base:
            return lead

        found_emails: list[str] = []
        found_owner = ""
        found_phone = ""

        for path in _CANDIDATE_PATHS[: self.max_pages]:
            url = base.rstrip("/") + path
            html = self._fetch(url)
            if not html:
                continue
            soup = BeautifulSoup(html, "lxml")
            text = soup.get_text(" ", strip=True)

            found_emails.extend(self._extract_emails(html, lead.domain))
            if not found_owner:
                found_owner = self._extract_owner(text)
            if not found_phone:
                found_phone = self._extract_phone(text)

            # Stop early if we already have a good personal email + owner.
            if found_owner and any(self._is_personal(e) for e in found_emails):
                break

        self._apply(lead, found_emails, found_owner, found_phone)
        return lead

    # ------------------------------------------------------------------ #
    def _normalize(self, website: str) -> str:
        w = website.strip()
        if not w:
            return ""
        if not w.startswith(("http://", "https://")):
            w = "https://" + w
        return w

    def _fetch(self, url: str) -> str:
        try:
            resp = self._session.get(url, timeout=self.timeout, allow_redirects=True)
            if resp.status_code == 200 and "text/html" in resp.headers.get("Content-Type", ""):
                return resp.text
        except requests.RequestException:
            pass
        return ""

    def _extract_emails(self, html: str, domain: str) -> list[str]:
        candidates = set()
        for match in _EMAIL_RE.findall(html):
            m = match.lower()
            if m.endswith(_JUNK_EMAIL_SUFFIXES):
                continue
            if "@" not in m or "." not in m.split("@")[1]:
                continue
            candidates.add(m)
        # Prefer emails on the business's own domain if we know it.
        if domain:
            on_domain = [e for e in candidates if e.endswith("@" + domain) or domain in e]
            if on_domain:
                return sorted(on_domain)
        return sorted(candidates)

    def _extract_owner(self, text: str) -> str:
        for pat in _OWNER_PATTERNS:
            m = pat.search(text)
            if m:
                name = m.group(1).strip()
                # Guard against matching common non-names.
                if len(name.split()) == 2 and name.lower() not in {"privacy policy", "terms conditions"}:
                    return name
        return ""

    def _extract_phone(self, text: str) -> str:
        # Loose grab; validation module formats to E.164 properly later.
        m = re.search(r"(\+?\d[\d\-\.\s\(\)]{7,}\d)", text)
        return m.group(1).strip() if m else ""

    def _is_personal(self, email: str) -> bool:
        prefix = email.split("@")[0].split("+")[0].strip(".").lower()
        # Personal if the prefix isn't a known role word and looks name-like.
        return prefix not in _ROLE_PREFIXES

    def _apply(self, lead: Lead, emails: list[str], owner: str, phone: str) -> None:
        notes: list[str] = []
        if emails and not lead.email:
            # Choose best: personal email first, else the first role email.
            personal = [e for e in emails if self._is_personal(e)]
            lead.email = personal[0] if personal else emails[0]
            notes.append(f"email via site crawl ({'personal' if personal else 'role'})")
        if owner and not lead.contact_name:
            lead.contact_name = owner
            notes.append("owner via site crawl")
        if phone and not lead.phone:
            lead.phone = phone
            notes.append("phone via site crawl")
        if notes:
            existing = (lead.notes + "; ") if lead.notes else ""
            lead.notes = existing + "; ".join(notes)


class HunterEnricher:
    """
    Optional Hunter.io enrichment (free tier: 25 searches/mo). Runs only if a
    key is configured. Fills email + contact name from the business domain.
    """

    def __init__(self, api_key: str) -> None:
        self.api_key = api_key
        self._session = requests.Session()

    def is_available(self) -> bool:
        return bool(self.api_key)

    def enrich(self, lead: Lead) -> Lead:
        if not self.is_available() or lead.email or not lead.domain:
            return lead
        try:
            resp = self._session.get(
                "https://api.hunter.io/v2/domain-search",
                params={"domain": lead.domain, "api_key": self.api_key, "limit": 5},
                timeout=15,
            )
            resp.raise_for_status()
            data = resp.json().get("data", {})
        except (requests.RequestException, ValueError) as exc:
            log.warning("Hunter.io lookup failed for %s: %s", lead.domain, exc)
            return lead

        emails = data.get("emails", [])
        if not emails:
            return lead
        # Prefer entries with a first/last name and higher confidence.
        emails.sort(key=lambda e: (bool(e.get("first_name")), e.get("confidence", 0)), reverse=True)
        best = emails[0]
        lead.email = best.get("value", "")
        first, last = best.get("first_name", ""), best.get("last_name", "")
        if first and not lead.contact_name:
            lead.contact_name = f"{first} {last}".strip()
        lead.notes = (lead.notes + "; " if lead.notes else "") + "enriched via Hunter.io"
        return lead


def enrich_leads(
    leads: Iterable[Lead],
    crawl_website: bool = True,
    max_pages: int = 5,
    timeout: int = 12,
    hunter_key: str = "",
    on_lead: Callable[[Lead], None] | None = None,
) -> list[Lead]:
    """
    Convenience batch enricher used by the pipeline.

    `on_lead` is called with each lead as soon as it is enriched. The pipeline
    uses it to persist progress incrementally, so a crash or Ctrl+C part-way
    through a long crawl doesn't discard the work already done.
    """
    crawler = WebsiteCrawler(max_pages=max_pages, timeout=timeout) if crawl_website else None
    hunter = HunterEnricher(hunter_key) if hunter_key else None
    out: list[Lead] = []
    for lead in leads:
        if crawler:
            lead = crawler.enrich(lead)
        if hunter and not lead.email:
            lead = hunter.enrich(lead)
        out.append(lead)
        if on_lead:
            on_lead(lead)
    return out
