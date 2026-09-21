"""
Command-line interface for the FixGenie outreach pipeline.

Usage examples (after `pip install -r requirements.txt`):

    python -m fixgenie.cli status               # show staging DB counts
    python -m fixgenie.cli discover             # find businesses -> staging
    python -m fixgenie.cli enrich               # crawl sites for email/owner
    python -m fixgenie.cli validate             # validate email + phone
    python -m fixgenie.cli push                 # dedup + append to Google Sheet
    python -m fixgenie.cli outreach --dry-run   # preview emails (no send)
    python -m fixgenie.cli outreach             # actually send the sequence
    python -m fixgenie.cli run-all --outreach --dry-run   # full pipeline

Design: thin CLI. All real logic lives in pipeline.py / the stage modules, so
the same functions can be called from n8n (via a small HTTP wrapper), GitHub
Actions, or cron without going through Click.
"""
from __future__ import annotations

import click

from fixgenie.common.config import settings
from fixgenie.common.console import console, make_table
from fixgenie.common.logging_setup import get_logger
from fixgenie.storage.staging_db import StagingDB

log = get_logger("fixgenie.cli")


def _db() -> StagingDB:
    settings.ensure_dirs()
    return StagingDB(settings.staging_db_path)


@click.group()
def cli() -> None:
    """FixGenie automated lead-gen & outreach pipeline."""


@cli.command()
def status() -> None:
    """Show how many leads sit at each pipeline stage."""
    db = _db()
    counts = db.counts_by_stage()
    table = make_table(title="FixGenie staging DB")
    table.add_column("Stage", style="cyan")
    table.add_column("Leads", justify="right", style="green")
    for stage in ("new", "enriched", "validated", "pushed", "duplicate"):
        table.add_row(stage, str(counts.get(stage, 0)))
    console.print(table)
    console.print(f"[dim]Sheet: {settings.google_sheet_name} | "
                  f"Provider: {settings.email_provider} | "
                  f"Places API: {'yes' if settings.has_google_places else 'no'} | "
                  f"Hunter: {'yes' if settings.has_hunter else 'no'}[/dim]")


@cli.command()
@click.option("--scrape", is_flag=True, help="Also use the opt-in directory scraper.")
def discover(scrape: bool) -> None:
    """Discover businesses for every target in campaigns.yaml."""
    from fixgenie.pipeline import stage_discover

    n = stage_discover(_db(), use_scraper=scrape)
    console.print(f"[green]Discovered {n} new leads.[/green]")


@cli.command(name="import-excel")
@click.option("--file", "file_path", required=True, help="Path to the .xlsx of scraped leads.")
@click.option("--sheet", "sheets", multiple=True,
              help="Specific sheet(s) to import. Repeatable. Default: all lead sheets.")
def import_excel(file_path: str, sheets: tuple[str, ...]) -> None:
    """Import already-scraped leads from an Excel file into staging."""
    from pathlib import Path

    from fixgenie.storage.excel_import import import_excel_to_staging

    n = import_excel_to_staging(Path(file_path), _db(), sheets=list(sheets) or None)
    console.print(f"[green]Imported {n} new leads from {Path(file_path).name} into staging.[/green]")
    console.print("[dim]Next: run 'enrich' to find real emails, then 'validate', then 'push'.[/dim]")


@cli.command()
def enrich() -> None:
    """Enrich staged leads (website crawl + optional Hunter.io)."""
    from fixgenie.pipeline import stage_enrich

    stage_enrich(_db())


@cli.command()
def validate() -> None:
    """Validate emails (syntax + MX) and format phones to E.164."""
    from fixgenie.pipeline import stage_validate

    stage_validate(_db())


@cli.command()
def push() -> None:
    """De-duplicate and append clean leads to the Google Sheet."""
    from fixgenie.pipeline import stage_push

    n = stage_push(_db())
    console.print(f"[green]Pushed {n} new leads to '{settings.google_sheet_name}'.[/green]")


@cli.command()
@click.option("--dry-run", is_flag=True, help="Render + print emails without sending.")
def outreach(dry_run: bool) -> None:
    """Send the outreach sequence to eligible leads in the Sheet."""
    from fixgenie.pipeline import stage_outreach

    stage_outreach(dry_run=dry_run)


@cli.command()
@click.option("--email", required=True, help="Address to add to the suppression list.")
def unsubscribe(email: str) -> None:
    """Manually add an address to the do-not-contact suppression list."""
    from fixgenie.outreach.compliance import SuppressionList

    SuppressionList(settings.suppression_path).add(email, reason="manual")
    console.print(f"[yellow]{email} will no longer be contacted.[/yellow]")


@cli.command(name="run-all")
@click.option("--scrape", is_flag=True, help="Include the opt-in directory scraper.")
@click.option("--outreach", "do_outreach", is_flag=True, help="Also run the outreach stage.")
@click.option("--dry-run", is_flag=True, help="Preview outreach without sending.")
def run_all_cmd(scrape: bool, do_outreach: bool, dry_run: bool) -> None:
    """Run discover -> enrich -> validate -> push (-> outreach) end to end."""
    from fixgenie.pipeline import run_all

    run_all(_db(), use_scraper=scrape, outreach=do_outreach, dry_run=dry_run)


if __name__ == "__main__":
    cli()
