"""
Pipeline orchestration - the glue that runs each stage in order.

Stages (mirrors Section 2 architecture):
    discover -> enrich -> validate -> dedup+push -> outreach

Each stage reads/writes the SQLite staging DB, so you can run them independently
(e.g. discover nightly, outreach every morning) or all at once with `run-all`.
Google Sheets is written only at the push stage, keeping API calls batched.
"""
from __future__ import annotations

from fixgenie.common.config import settings
from fixgenie.common.logging_setup import get_logger
from fixgenie.common.models import Lead
from fixgenie.discovery.base import SearchTarget
from fixgenie.discovery.overpass_source import OverpassSource
from fixgenie.discovery.places_source import GooglePlacesSource
from fixgenie.enrichment.website_crawler import enrich_leads
from fixgenie.storage.dedup import filter_new_leads
from fixgenie.storage.staging_db import StagingDB
from fixgenie.validation.validators import validate_leads

log = get_logger(__name__)


def _targets() -> list[SearchTarget]:
    raw = settings.campaigns.get("targets", [])
    return [SearchTarget.from_dict(t) for t in raw]


def _build_sources(use_scraper: bool = False):
    """Instantiate discovery sources named in campaigns.yaml + availability."""
    disc_cfg = settings.campaigns.get("discovery", {})
    names = disc_cfg.get("sources", ["overpass"])
    delay = float(disc_cfg.get("polite_delay_seconds", 2))
    sources = []
    for name in names:
        if name == "overpass":
            sources.append(OverpassSource(settings.overpass_endpoint, polite_delay=delay))
        elif name == "google_places" and settings.has_google_places:
            sources.append(GooglePlacesSource(settings.google_places_api_key, polite_delay=delay))
        elif name == "google_places":
            log.info("Skipping google_places source (no API key configured).")
    # Directory scraper is opt-in and needs a site-specific SelectorProfile,
    # so it is not auto-wired here. See directory_scraper.py to enable.
    if use_scraper:
        log.warning(
            "Scraper requested but no SelectorProfile is configured. "
            "Edit pipeline._build_sources to add a DirectoryScraper for a "
            "specific public directory you have permission to use."
        )
    return sources


# ---------------------------------------------------------------------- #
# Stages
# ---------------------------------------------------------------------- #
def stage_discover(db: StagingDB, use_scraper: bool = False) -> int:
    sources = _build_sources(use_scraper)
    if not sources:
        log.error("No discovery sources available.")
        return 0
    targets = _targets()
    if not targets:
        log.error("No targets defined in campaigns.yaml.")
        return 0

    new_count = 0
    for target in targets:
        for source in sources:
            if not source.is_available():
                continue
            for lead in source.search(target):
                is_new = db.upsert(lead, stage="new")
                if is_new:
                    new_count += 1
    log.info("Discovery complete: %d new raw leads staged.", new_count)
    return new_count


def stage_enrich(db: StagingDB) -> int:
    enr_cfg = settings.campaigns.get("enrichment", {})
    leads = db.get_by_stage("new")
    if not leads:
        log.info("Nothing to enrich.")
        return 0
    enriched = enrich_leads(
        leads,
        crawl_website=bool(enr_cfg.get("crawl_website", True)),
        max_pages=int(enr_cfg.get("max_pages_per_site", 5)),
        timeout=int(enr_cfg.get("request_timeout", 12)),
        hunter_key=settings.hunter_api_key if enr_cfg.get("use_hunter") else "",
    )
    for lead in enriched:
        db.upsert(lead, stage="enriched")
    log.info("Enrichment complete: %d leads.", len(enriched))
    return len(enriched)


def stage_validate(db: StagingDB) -> int:
    val_cfg = settings.campaigns.get("validation", {})
    leads = db.get_by_stage("enriched")
    if not leads:
        log.info("Nothing to validate.")
        return 0
    validated = validate_leads(
        leads,
        require_mx=bool(val_cfg.get("require_mx", True)),
        role_is_risky=bool(val_cfg.get("treat_role_email_as_risky", True)),
    )
    for lead in validated:
        db.upsert(lead, stage="validated")
    log.info("Validation complete: %d leads.", len(validated))
    return len(validated)


def stage_push(db: StagingDB) -> int:
    """De-dup validated leads against the Sheet, then append the new ones."""
    from fixgenie.storage.sheets import SheetsClient

    leads = db.get_by_stage("validated")
    if not leads:
        log.info("Nothing to push.")
        return 0

    dedup_cfg = settings.campaigns.get("dedup", {})
    threshold = int(dedup_cfg.get("name_similarity_threshold", 88))

    client = SheetsClient(
        settings.resolve_path(settings.google_service_account_json),
        settings.google_sheet_name,
    )
    existing = client.load_all()
    new_leads, dropped = filter_new_leads(leads, existing, name_threshold=threshold)

    pushed = client.append_leads_bulk(new_leads)
    for lead in new_leads:
        db.set_stage(lead.lead_id, "pushed")
    # Leads that were duplicates still move out of 'validated' so they aren't
    # re-processed forever.
    for lead in leads:
        if lead not in new_leads:
            db.set_stage(lead.lead_id, "duplicate")
    log.info("Push complete: %d appended to Sheet, %d duplicates skipped.", pushed, dropped)
    return pushed


def stage_outreach(dry_run: bool = False) -> None:
    """Read leads from the Sheet and run the outreach sequence."""
    from fixgenie.outreach.engine import OutreachEngine
    from fixgenie.outreach.senders import build_sender
    from fixgenie.storage.sheets import SheetsClient

    out_cfg = settings.campaigns.get("outreach", {})
    if not out_cfg.get("enabled", True):
        log.info("Outreach disabled in campaigns.yaml.")
        return

    client = SheetsClient(
        settings.resolve_path(settings.google_service_account_json),
        settings.google_sheet_name,
    )
    leads = client.load_all()

    sender = build_sender(settings)
    if not dry_run and not sender.is_configured():
        log.error("Email sender not configured. Set EMAIL_PROVIDER + credentials in .env, "
                  "or run with --dry-run to preview.")
        return

    engine = OutreachEngine(
        sender=sender,
        templates_dir=settings.templates_dir,
        sequence=OutreachEngine.sequence_from_config(settings.campaigns),
        settings=settings,
        dry_run=dry_run,
    )
    engine.run(
        leads,
        persist=client.update_lead,
        log_event=client.log_event,
        send_only_if_status_in=out_cfg.get("send_only_if_status_in", ["Valid"]),
    )


def run_all(db: StagingDB, use_scraper: bool = False, outreach: bool = False, dry_run: bool = False) -> None:
    stage_discover(db, use_scraper=use_scraper)
    stage_enrich(db)
    stage_validate(db)
    stage_push(db)
    if outreach:
        stage_outreach(dry_run=dry_run)
