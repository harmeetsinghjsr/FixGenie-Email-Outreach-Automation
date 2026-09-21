"""
Outreach engine - renders, sends, rate-limits, and tracks the email sequence.

Responsibilities:
  - Decide which leads are due for which step of the cadence (Section 11).
  - Render the Jinja2 template with personalization tokens + append the required
    legal footer (compliance.py).
  - Enforce the daily send cap and human-like delays (Section 11 / 21).
  - Skip anyone on the suppression list or without a Valid email.
  - Update each lead's status/timestamps and write an Outreach Log event so the
    Sheet stays the source of truth (Section 10).

It does NOT talk to Sheets directly - it takes a callback to persist a lead, so
the same engine works for the SQLite path and the Sheets path (and is testable).
"""
from __future__ import annotations

import random
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from jinja2 import Environment, FileSystemLoader, select_autoescape

from fixgenie.common.logging_setup import get_logger
from fixgenie.common.models import EmailStatus, Lead, OutreachStatus
from fixgenie.outreach import compliance
from fixgenie.outreach.senders import EmailSender

log = get_logger(__name__)


@dataclass
class SequenceStep:
    step: int
    wait_days: int
    template: str
    subject: str


@dataclass
class OutreachResult:
    attempted: int = 0
    sent: int = 0
    skipped: int = 0
    failed: int = 0


class OutreachEngine:
    def __init__(
        self,
        sender: EmailSender,
        templates_dir: Path,
        sequence: list[SequenceStep],
        settings,
        dry_run: bool = False,
    ) -> None:
        self.sender = sender
        self.sequence = sorted(sequence, key=lambda s: s.step)
        self.settings = settings
        self.dry_run = dry_run
        self.suppression = compliance.SuppressionList(settings.suppression_path)
        self._env = Environment(
            loader=FileSystemLoader(str(templates_dir)),
            autoescape=select_autoescape(enabled_extensions=("html",)),
        )
        self._subject_env = Environment(autoescape=False)  # subjects are plain text

    # ------------------------------------------------------------------ #
    def _context(self, lead: Lead) -> dict:
        city = lead.city_region.split(",")[0].strip() if lead.city_region else ""
        return {
            "business_name": lead.business_name,
            "contact_first_name": lead.contact_first_name,
            "contact_name": lead.contact_name,
            "category": lead.category or "business",
            "city": city,
            "sender_name": self.settings.sender_name,
            "sender_company": self.settings.sender_company,
        }

    def _due_step(self, lead: Lead, send_only_if_status_in: list[str]) -> SequenceStep | None:
        """Return the next sequence step this lead is due for, or None."""
        # Gate on email validity.
        if lead.email_status not in send_only_if_status_in:
            return None
        # Terminal states never get more email.
        if lead.outreach_status in (
            OutreachStatus.REPLIED.value,
            OutreachStatus.UNSUBSCRIBED.value,
            OutreachStatus.BOUNCED.value,
        ):
            return None
        # Suppression check.
        if self.suppression.contains(lead.email):
            return None

        next_step_num = lead.sequence_step + 1
        step = next((s for s in self.sequence if s.step == next_step_num), None)
        if step is None:
            return None  # sequence exhausted

        # Respect wait_days between touches.
        if lead.last_contacted_date and step.wait_days > 0:
            try:
                last = datetime.fromisoformat(lead.last_contacted_date)
                elapsed_days = (datetime.now(timezone.utc) - last).days
                if elapsed_days < step.wait_days:
                    return None
            except ValueError:
                pass
        return step

    def _render(self, lead: Lead, step: SequenceStep) -> tuple[str, str, str]:
        """Return (subject, text_body, html_body) fully rendered with footer."""
        ctx = self._context(lead)
        subject = self._subject_env.from_string(step.subject).render(**ctx)
        body = self._env.get_template(step.template).render(**ctx)

        unsub = compliance.unsubscribe_link(self.settings.unsubscribe_base_url, lead.email)
        text_footer = compliance.legal_footer_text(
            self.settings.sender_name,
            self.settings.sender_company,
            self.settings.sender_postal_address,
            unsub,
        )
        html_footer = compliance.legal_footer_html(
            self.settings.sender_name,
            self.settings.sender_company,
            self.settings.sender_postal_address,
            unsub,
        )
        text_body = body + text_footer
        html_body = body.replace("\n", "<br>") + html_footer
        return subject, text_body, html_body

    # ------------------------------------------------------------------ #
    def run(
        self,
        leads: list[Lead],
        persist: Callable[[Lead], None],
        log_event: Callable[[Lead, str, str], None] | None = None,
        send_only_if_status_in: list[str] | None = None,
    ) -> OutreachResult:
        """
        Process a batch of leads. `persist` writes the updated lead back to the
        store (Sheets/DB). `log_event` records an audit event (optional).
        """
        send_only_if_status_in = send_only_if_status_in or [EmailStatus.VALID.value]
        result = OutreachResult()
        sent_this_run = 0

        for lead in leads:
            if sent_this_run >= self.settings.daily_send_limit:
                log.info("Daily send limit (%d) reached; stopping.", self.settings.daily_send_limit)
                break

            step = self._due_step(lead, send_only_if_status_in)
            if step is None:
                result.skipped += 1
                continue

            result.attempted += 1
            subject, text_body, html_body = self._render(lead, step)

            if self.dry_run:
                log.info("[DRY RUN] Would send step %d to %s <%s> | Subject: %s",
                         step.step, lead.business_name, lead.email, subject)
                result.sent += 1
                sent_this_run += 1
                # In dry-run we don't mutate persisted status.
                continue

            ok, detail = self.sender.send(
                lead.email, lead.contact_name, subject, text_body, html_body
            )
            self._apply_result(lead, step, ok, detail)
            if log_event:
                log_event(lead, "SENT" if ok else "SEND_FAILED", f"step {step.step}: {detail}")
            persist(lead)

            if ok:
                result.sent += 1
                sent_this_run += 1
                self._polite_delay()
            else:
                result.failed += 1
                log.error("Send failed for %s: %s", lead.email, detail)

        log.info(
            "Outreach done: sent=%d skipped=%d failed=%d",
            result.sent, result.skipped, result.failed,
        )
        return result

    def _apply_result(self, lead: Lead, step: SequenceStep, ok: bool, detail: str) -> None:
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        lead.send_attempts += 1
        lead.template_version = step.template
        if ok:
            lead.sequence_step = step.step
            lead.outreach_status = OutreachStatus.SENT.value
            lead.last_contacted_date = now
            lead.send_error = ""
            if step.step == 1:
                lead.auto_email_sent = True
                lead.auto_email_sent_at = now
        else:
            lead.outreach_status = OutreachStatus.SEND_FAILED.value
            lead.send_error = detail[:250]

    def _polite_delay(self) -> None:
        base = self.settings.send_delay_seconds
        jitter = base * 0.4
        time.sleep(random.uniform(max(1, base - jitter), base + jitter))

    @classmethod
    def sequence_from_config(cls, campaigns: dict) -> list[SequenceStep]:
        raw = (campaigns.get("outreach", {}) or {}).get("sequence", [])
        return [
            SequenceStep(
                step=int(s["step"]),
                wait_days=int(s.get("wait_days", 0)),
                template=s["template"],
                subject=s.get("subject", "Hello from FixGenie"),
            )
            for s in raw
        ]
