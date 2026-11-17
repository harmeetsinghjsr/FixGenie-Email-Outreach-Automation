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

# The LLM gateway is reached over the public internet; a dropped DNS lookup or
# reset connection must not silently cost us a lead (a transient blip once
# failed 171 of 433 leads in a single run).
_NET_ATTEMPTS = 4
_NET_BASE_DELAY = 3.0  # seconds; doubles -> 3, 6, 12

_SYSTEM = (
    "You write concise, genuine, highly personalized cold-email openers. You are given "
    "messy scraped data about ONE small business. Your job is to find a unique, specific, "
    "genuine hook for THAT business — not a generic template. Reference the business's "
    "actual location, what kind of work they do, or a specific challenge their industry "
    "faces. NEVER write a boilerplate opener that could apply to any business in that "
    "category. Each opener must be distinctly different from the others in both wording "
    "and angle. Use plain, conversational, first-person tone. Respond with STRICT JSON "
    "only - no markdown, no commentary."
)

_USER_TEMPLATE = """Here is what I found about ONE business I want to write to:

name: {name}
category: {category}
address: {address}
city/region: {city}
website: {website}
domain: {domain}
phone: {phone}
snippet from their site: {snippet}
source URL: {source_url}

Your company ({company}) helps small businesses like this one automate repetitive work:
  - booking follow-ups and appointment reminders
  - invoicing (creating, sending, chasing, reconciling)
  - data entry (leads, appointments, payments)
  - email/SMS sequences that follow up automatically
  - phone call routing and voicemail → email transcription

CRITICAL: Write THREE openers, each completely different from the others — different
wording, different angle, different hook. Do NOT sound like a template. Do NOT open
with "I noticed you're in [city] doing [category]". Find a genuine, specific reason
to reach out to THIS business. Use plain ASCII only (no smart quotes, no em dashes).

Return JSON exactly like:
{{"company_name": "...", "opener": "...", "followup": "...", "breakup": "..."}}

company_name rules:
- The real business name, cleaned up (drop "Contact"/"Home"/taglines/duplicate words).
- If the name is a call-to-action or unclear, infer the brand from the website domain.
- Keep it short.

opener rules (email 1, first line):
- Reference something specific: their exact location, a specific industry quirk, a
  time-of-year angle, something their competitors probably struggle with, or a
  detail from their business type that creates a natural hook.
- Example: "I pass by your Brickell office a lot — real estate teams down here are
  still chasing listing leads on spreadsheets in 2024?"
- Do NOT be generic. No "I help businesses automate work" — that goes in the body.
- Max 220 characters.

followup rules (email 2):
- DIFFERENT angle from the opener. Don't repeat the same hook.
- Reference a specific scenario, pain point, or use case relevant to their industry.
- Example: "Quick question: how much time does your team spend each week manually
  chasing down signed agreements?"
- Max 220 characters.

breakup rules (email 3):
- Low-pressure "I'll close the loop" tone, but specific to them, not generic.
- Reference their location/industry specifically.
- Max 220 characters.
"""


def _call_llm(name: str, category: str, address: str, city: str,
            website: str, domain: str, phone: str, snippet: str,
            source_url: str) -> dict:
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
                address=address or "(none)", city=city or "(unknown)",
                website=website or "(none)", domain=domain or "(none)",
                phone=phone or "(none)", snippet=(snippet or "(none)")[:400],
                source_url=source_url or "(none)",
                company=settings.sender_company,
            ),
        }],
    }
    # Retry the POST itself: a DNS/connection blip here is transient, while a
    # 4xx (bad key, bad model) is not and should surface immediately.
    delay = _NET_BASE_DELAY
    for attempt in range(1, _NET_ATTEMPTS + 1):
        try:
            resp = requests.post(url, headers=headers, json=body, timeout=60)
            break
        except (requests.ConnectionError, requests.Timeout) as exc:
            if attempt == _NET_ATTEMPTS:
                raise
            print(f"    LLM network error (attempt {attempt}/{_NET_ATTEMPTS}): "
                  f"{type(exc).__name__}; retrying in {delay:.0f}s")
            time.sleep(delay)
            delay *= 2
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
    ap.add_argument("--no-dedup", action="store_true",
                    help="Don't skip leads already in the Sheet (push still dedups).")
    args = ap.parse_args()

    if not settings.has_llm:
        sys.exit("LLM not configured. Set LLM_BASE_URL + LLM_API_KEY in .env.")

    settings.ensure_dirs()
    db = StagingDB(settings.staging_db_path)
    if not args.no_dedup:
        # Drop leads the Sheet already has BEFORE paying for LLM calls on them;
        # they also skip enrich/validate, since those read the same stage.
        from fixgenie.pipeline import stage_predupe

        skipped = stage_predupe(db, stage=args.stage)
        print(f"Skipped {skipped} leads already in the Sheet.")
    leads = db.get_by_stage(args.stage)
    # Skip leads with no email - they can't be emailed, so don't spend LLM calls
    # (and don't re-personalize ones that already have an opener).
    leads = [l for l in leads if l.email and not l.pitch_hook]
    if args.limit:
        leads = leads[: args.limit]
    if not leads:
        print(f"No un-personalized leads with an email at stage '{args.stage}'.")
        return

    from urllib.parse import urlparse

    from fixgenie.common.network import wait_for_network

    llm_host = urlparse(settings.llm_base_url).hostname or ""
    ok = fail = 0
    for i, lead in enumerate(leads, 1):
        city = lead.city_region.split(",")[0].strip() if lead.city_region else ""
        try:
            result = None
            waited = False
            attempt = 0
            while True:  # thinking models occasionally return an empty reply
                try:
                    result = _call_llm(
                        lead.business_name, lead.category, lead.address, city,
                        lead.website, lead.domain, lead.phone, lead.raw_snippet,
                        lead.source_url,
                    )
                    break
                except (ValueError, json.JSONDecodeError):
                    attempt += 1
                    if attempt == 3:
                        raise
                    time.sleep(1.0)
                except (requests.ConnectionError, requests.Timeout):
                    # _call_llm already retried for ~20s. A longer outage would
                    # otherwise fail every remaining lead in a few seconds each
                    # (68 leads lost their opener this way on 17 Nov), so wait
                    # for the network once per lead, then try it again.
                    if waited or not llm_host or not wait_for_network(
                        (llm_host,), max_wait=900, log=lambda m: print(f"    {m}")
                    ):
                        raise
                    waited = True
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
