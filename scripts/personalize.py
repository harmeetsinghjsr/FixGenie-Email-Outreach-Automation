"""
LLM personalization step.

For each staged lead it asks an LLM (via an Anthropic-Messages-format gateway,
e.g. agentrouter.org) for:
  - a clean company name (fixes scraped junk like "Start the Conversation"), and
  - one tailored opener sentence, in your voice, used as the email's first line.

It writes those onto the lead (business_name + pitch_hook). Run it AFTER finding
leads and BEFORE pushing:

    python scripts/exa_leads.py --industry "real estate" --city "Miami"
    python scripts/personalize.py                 # <-- this step
    python -m fixgenie.cli enrich
    python -m fixgenie.cli validate
    python -m fixgenie.cli push

Config (in .env):
    LLM_BASE_URL, LLM_API_KEY, LLM_MODEL, LLM_USER_AGENT
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time

import requests

from fixgenie.common.config import settings
from fixgenie.common.models import Lead, clean_business_name
from fixgenie.storage.staging_db import StagingDB

_SYSTEM = (
    "You write concise, genuine cold-email openers for {company}, a firm that helps "
    "businesses automate repetitive manual work (booking follow-ups, invoicing, data "
    "entry). You are given messy scraped data about ONE business. Respond with STRICT "
    "JSON only - no markdown, no commentary."
)

_USER_TEMPLATE = """Business (scraped, may be messy):
- name: {name}
- category: {category}
- city: {city}
- website: {website}
- snippet from their site: {snippet}

Return JSON exactly like:
{{"company_name": "...", "opener": "...", "followup": "...", "breakup": "..."}}

Rules:
- company_name: the real business name, cleaned up (drop "Contact"/"Home"/taglines/
  duplicate words). If the name is a call-to-action or unclear, infer the brand from
  the website domain. Keep it short.
- opener / followup / breakup: each is ONE natural sentence in MY first-person voice,
  the FIRST line of a 3-email cold sequence to this business:
    * opener   = email 1, a fresh intro referencing what THIS business does.
    * followup = email 2 (a few days later), a warm nudge - DIFFERENT wording from
      the opener, e.g. circling back with a specific angle.
    * breakup  = email 3 (last one), a low-pressure "I'll close the loop" tone.
  For all three: no greeting, no sign-off, use category/city/snippet, do NOT invent
  facts, max 200 characters each, sound human (not salesy/cheesy), and use plain
  ASCII punctuation only - hyphens or periods, NEVER em dashes or smart/curly quotes.
"""


def _call_llm(name: str, category: str, city: str, website: str, snippet: str) -> dict:
    url = settings.llm_base_url.rstrip("/") + "/v1/messages"
    headers = {
        "content-type": "application/json",
        "anthropic-version": "2023-06-01",
        "x-api-key": settings.llm_api_key,
        "authorization": "Bearer " + settings.llm_api_key,
        "user-agent": settings.llm_user_agent,
    }
    body = {
        "model": settings.llm_model,
        # Generous, because "thinking" models (e.g. deepseek) spend tokens on a
        # reasoning block before the JSON, and we now ask for 3 openers.
        "max_tokens": 1600,
        "system": _SYSTEM.format(company=settings.sender_company),
        "messages": [{
            "role": "user",
            "content": _USER_TEMPLATE.format(
                name=name or "(unknown)", category=category or "(unknown)",
                city=city or "(unknown)", website=website or "(none)",
                snippet=(snippet or "(none)")[:400],
            ),
        }],
    }
    resp = requests.post(url, headers=headers, json=body, timeout=60)
    resp.raise_for_status()
    # Decode as UTF-8 explicitly: some gateways omit the charset, and requests'
    # guessed encoding can mangle em dashes/smart quotes into U+FFFD.
    data = json.loads(resp.content.decode("utf-8", errors="replace"))
    # Anthropic format: content is a list of blocks; keep only text blocks.
    text = "".join(b.get("text", "") for b in data.get("content", []) if b.get("type") == "text")
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        raise ValueError(f"no JSON in model reply: {text[:120]!r}")
    return json.loads(m.group(0))


def main() -> None:
    ap = argparse.ArgumentParser(description="Add a clean name + tailored opener to leads via an LLM.")
    ap.add_argument("--stage", default="new", help="Which staged leads to personalize (default: new).")
    ap.add_argument("--limit", type=int, default=None, help="Only process the first N.")
    ap.add_argument("--delay", type=float, default=0.5, help="Seconds between calls.")
    args = ap.parse_args()

    if not settings.has_llm:
        sys.exit("LLM not configured. Set LLM_BASE_URL + LLM_API_KEY in .env.")

    settings.ensure_dirs()
    db = StagingDB(settings.staging_db_path)
    leads = db.get_by_stage(args.stage)
    # Skip leads with no email - they can't be emailed, so don't spend LLM calls
    # (and don't re-personalize ones that already have an opener).
    leads = [l for l in leads if l.email and not l.pitch_hook]
    if args.limit:
        leads = leads[: args.limit]
    if not leads:
        print(f"No un-personalized leads with an email at stage '{args.stage}'.")
        return

    ok = fail = 0
    for i, lead in enumerate(leads, 1):
        city = lead.city_region.split(",")[0].strip() if lead.city_region else ""
        try:
            result = None
            for attempt in range(3):  # thinking models occasionally return an empty reply
                try:
                    result = _call_llm(lead.business_name, lead.category, city,
                                       lead.website, lead.raw_snippet)
                    break
                except (ValueError, json.JSONDecodeError):
                    if attempt == 2:
                        raise
                    time.sleep(1.0)
            company = str(result.get("company_name", "")).strip()
            if company:
                lead.business_name = company[:80]
            if result.get("opener"):
                lead.pitch_hook = str(result["opener"]).strip()[:220]
            if result.get("followup"):
                lead.pitch_hook2 = str(result["followup"]).strip()[:220]
            if result.get("breakup"):
                lead.pitch_hook3 = str(result["breakup"]).strip()[:220]
            db.upsert(lead, stage=args.stage)
            ok += 1
            print(f"  [{i}/{len(leads)}] {lead.business_name[:34]:34} | {(lead.pitch_hook or '')[:70]}")
        except Exception as exc:  # noqa: BLE001 - keep going on a single bad lead
            fail += 1
            # Fall back to a cleaned name so the lead is still usable.
            cleaned = clean_business_name(lead.business_name)
            if cleaned and cleaned != lead.business_name:
                lead.business_name = cleaned
                db.upsert(lead, stage=args.stage)
            print(f"  [{i}/{len(leads)}] personalize failed: {type(exc).__name__}: {str(exc)[:80]}")
        time.sleep(args.delay)

    print(f"\nPersonalized {ok} leads ({fail} failed). Next: enrich -> validate -> push.")


if __name__ == "__main__":
    main()
