"""
Exa (via agent-reach / mcporter) lead finder.

Why this exists:
    The built-in OpenStreetMap discovery is free but rarely returns *emails*.
    Exa's web search finds businesses' actual "Contact" pages, which usually
    already contain the email, phone, and address. This script runs a few Exa
    searches, extracts leads, and stages them into the SAME SQLite DB the rest
    of the pipeline uses -- so `validate` -> `push` -> `outreach` all still work
    unchanged.

Prereqs (already set up once):
    npm install -g mcporter
    mcporter config add exa https://mcp.exa.ai/mcp --scope home

Usage:
    python scripts/exa_leads.py --industry "real estate" --city "Miami" --region "Florida"
    # then:
    python -m fixgenie.cli validate
    python -m fixgenie.cli push
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys

from fixgenie.common.config import settings
from fixgenie.common.models import EmailStatus, Lead
from fixgenie.storage.staging_db import StagingDB

# --- extraction patterns ---------------------------------------------------- #
_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
# A parenthesized all-digit phone token Exa emits, e.g. "(+13055985488)" / "(13055044235)"
_PHONE_PAREN_RE = re.compile(r"\(\+?1?(\d{10})\)")
# Fallback loose US phone, e.g. "(305) 598-5488" or "+1 305 504 4235"
_PHONE_LOOSE_RE = re.compile(r"\+?1?[\s.-]*\(?(\d{3})\)?[\s.-]*(\d{3})[\s.-]*(\d{4})")
# US street address line, e.g. "9415 Sunset Dr #236, Miami, FL 33173"
_ADDR_RE = re.compile(r"\d{1,6}\s+[\w.\- ]+?,\s*[\w.\- ]+,\s*[A-Z]{2}\s*\d{5}")

# Emails that are almost never a real business inbox -> skip.
_JUNK_EMAIL = re.compile(
    r"(sentry|example\.|\.png|\.jpg|\.gif|\.webp|wixpress|placeholder|@sentry|@2x)",
    re.I,
)
_JUNK_DOMAINS = {"domain.com", "email.com", "yourdomain.com"}


def _run_exa(query: str, num_results: int) -> str:
    """Call the Exa web_search_exa tool via mcporter and return its raw text."""
    mcporter = shutil.which("mcporter") or shutil.which("mcporter.cmd")
    if not mcporter:
        sys.exit(
            "mcporter not found on PATH. Install it once with:\n"
            "  npm install -g mcporter\n"
            "  mcporter config add exa https://mcp.exa.ai/mcp --scope home"
        )
    args = json.dumps({"query": query, "num_results": num_results})
    try:
        out = subprocess.run(
            [mcporter, "call", "exa", "web_search_exa", "--args", args],
            capture_output=True, text=True, timeout=90,
            encoding="utf-8", errors="replace",   # Exa output is UTF-8; avoid Windows cp1252 crash
        )
    except subprocess.TimeoutExpired:
        print(f"  ! Exa search timed out for: {query}")
        return ""
    return (out.stdout or "") + "\n" + (out.stderr or "")


def _blocks(raw: str) -> list[str]:
    """Split Exa's output into per-result blocks."""
    # Records are separated by a line that is just '---'.
    parts = re.split(r"\n-{3,}\n", raw)
    return [p for p in parts if "URL:" in p]


def _field(block: str, label: str) -> str:
    m = re.search(rf"^{label}:\s*(.+)$", block, re.M)
    return m.group(1).strip() if m else ""


def _clean_name(title: str, website: str) -> str:
    """Best-effort business name from a messy page title."""
    t = title
    # Drop common contact-page prefixes.
    t = re.sub(r"^\s*(contact us|contact|get in touch)\s*[-–—|:]*\s*", "", t, flags=re.I)
    # Split on separators and drop generic marketing segments.
    segs = [s.strip() for s in re.split(r"[|–—]", t) if s.strip()]
    generic = re.compile(r"^(home|contact.*|call .*|leading real estate.*|welcome.*)$", re.I)
    segs = [s for s in segs if not generic.match(s)]
    name = max(segs, key=len) if segs else t.strip()
    name = re.sub(r"\s+", " ", name).strip(" -–—|")
    if not name and website:
        # Fall back to the domain, e.g. floridarealtyofmiami.com -> Floridarealtyofmiami
        dom = re.sub(r"^https?://(www\.)?", "", website).split("/")[0]
        name = dom.split(".")[0].replace("-", " ").title()
    return name[:120]


def _pick_email(block: str) -> str:
    for m in _EMAIL_RE.findall(block):
        e = m.strip().rstrip(".").lower()
        if _JUNK_EMAIL.search(e):
            continue
        if e.split("@")[-1] in _JUNK_DOMAINS:
            continue
        return e
    return ""


def _pick_phone(block: str) -> str:
    m = _PHONE_PAREN_RE.search(block)
    if m:
        return "+1" + m.group(1)
    m = _PHONE_LOOSE_RE.search(block)
    if m:
        return "+1" + "".join(m.groups())
    return ""


def _pick_address(block: str) -> str:
    m = _ADDR_RE.search(block.replace("\n", " "))
    return m.group(0).strip() if m else ""


def _build_queries(industry: str, city: str, region: str, country: str,
                   custom_query: str) -> tuple[list[str], str]:
    """
    Decide what to search for and what to record as the lead's location.

    Three modes:
      1. --query "..."   : you write the search yourself (most control). Global.
      2. --industry only : global search for that industry (no city).
      3. --industry+--city: local search (the original behavior).
    """
    if custom_query:
        base = custom_query.strip()
        queries = [
            f"{base} contact email",
            f"{base} official website contact us email phone",
            f"{base} company contact details email",
        ]
        return queries, ""  # location unknown for a free-form global search

    place = " ".join(p for p in (city, region) if p).strip()
    if place:
        # Local mode.
        queries = [
            f"{industry} in {place} contact us email",
            f"best {industry} companies {place} contact email phone",
            f'"{industry}" {place} office contact address email',
        ]
        location = ", ".join(p for p in (city, region, country) if p)
        return queries, location

    # Global-by-industry mode.
    queries = [
        f"top {industry} companies contact email",
        f"leading {industry} startups official website contact us email",
        f"{industry} agencies worldwide contact details email phone",
    ]
    return queries, ""


def find_leads(industry: str, city: str, region: str, country: str,
               num_results: int, custom_query: str = "") -> list[Lead]:
    queries, place = _build_queries(industry, city, region, country, custom_query)
    category = custom_query or industry
    seen: dict[str, Lead] = {}   # keyed by email-or-website to dedup within run
    for q in queries:
        print(f"  Searching Exa: {q}")
        raw = _run_exa(q, num_results)
        for block in _blocks(raw):
            website = _field(block, "URL")
            email = _pick_email(block)
            phone = _pick_phone(block)
            if not (email or phone):
                continue  # a lead with no way to reach it is useless
            name = _clean_name(_field(block, "Title"), website)
            key = email or website
            if key in seen:
                # Merge: fill missing fields from the duplicate.
                ex = seen[key]
                ex.email = ex.email or email
                ex.phone = ex.phone or phone
                continue
            seen[key] = Lead(
                business_name=name,
                category=category,
                email=email,
                phone=phone,
                website=website,
                address=_pick_address(block),
                city_region=place,
                source="Exa (agent-reach)",
                source_url=website,
                email_status=EmailStatus.UNKNOWN.value,
            )
    return list(seen.values())


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Find leads (with emails) via Exa/agent-reach.",
        epilog='Examples:\n'
               '  Local:  --industry "real estate" --city "Miami" --region "Florida"\n'
               '  Global: --industry "SaaS company"\n'
               '  Custom: --query "AI automation startups in Europe hiring"',
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("--industry", default="", help='e.g. "real estate", "SaaS company"')
    ap.add_argument("--city", default="", help='e.g. "Miami" (leave empty to search globally)')
    ap.add_argument("--region", default="", help='e.g. "Florida"')
    ap.add_argument("--country", default="")
    ap.add_argument("--query", default="",
                    help='Write the whole search yourself, for full control. '
                         'Overrides --industry/--city.')
    ap.add_argument("--num", type=int, default=10, help="results per query (default 10)")
    args = ap.parse_args()

    if not args.industry and not args.query:
        ap.error("give either --industry (optionally with --city) or --query")

    settings.ensure_dirs()
    db = StagingDB(settings.staging_db_path)

    leads = find_leads(args.industry, args.city, args.region, args.country,
                       args.num, custom_query=args.query)
    if not leads:
        print("No leads with a contact method were found. Try a broader industry/city.")
        return

    new = sum(1 for lead in leads if db.upsert(lead, stage="new"))
    with_email = sum(1 for lead in leads if lead.email)

    print(f"\nStaged {new} new leads ({with_email} of {len(leads)} have an email).")
    print("Preview:")
    for lead in leads[:15]:
        print(f"  - {lead.business_name[:38]:38} "
              f"{(lead.email or '(no email)'):36} {lead.phone or ''}")
    print("\nNext:  python -m fixgenie.cli validate   then   python -m fixgenie.cli push")


if __name__ == "__main__":
    main()
