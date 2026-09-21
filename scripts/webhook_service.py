"""
Tiny HTTP webhook service (stdlib only) - two jobs:

  1. /health              -> readiness probe.
  2. /outreach/run        -> trigger the outreach stage on demand (POST).
                             This is what an n8n "HTTP Request" node calls in the
                             HYBRID setup: n8n handles discovery/scheduling, then
                             pings this endpoint to fire the Python send logic.
  3. /esp/webhook         -> receive open/click/bounce/unsubscribe events from
                             Brevo/SendGrid and update the Sheet + suppression
                             list (Section 19 step 8).

Deliberately dependency-free (uses http.server) so it runs anywhere with zero
install. For higher volume, put it behind gunicorn/uvicorn + FastAPI later.

SECURITY: set WEBHOOK_TOKEN in .env and pass it as `?token=` or an
`X-Webhook-Token` header. Requests without the right token are rejected. This
endpoint has NO other auth, so do not expose it publicly without the token
(and ideally a reverse proxy with TLS).
"""
from __future__ import annotations

import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from fixgenie.common.config import settings
from fixgenie.common.logging_setup import get_logger

log = get_logger("fixgenie.webhook")

_TOKEN = os.environ.get("WEBHOOK_TOKEN", "").strip()


class Handler(BaseHTTPRequestHandler):
    def _authorized(self, query: dict) -> bool:
        if not _TOKEN:
            return True  # no token configured -> allow (dev only)
        header = self.headers.get("X-Webhook-Token", "")
        q = (query.get("token", [""]) or [""])[0]
        return _TOKEN in (header, q)

    def _json(self, code: int, payload: dict) -> None:
        body = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    # --- silence default noisy logging; use our logger instead ---
    def log_message(self, *args) -> None:  # noqa: D401
        return

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/health":
            self._json(200, {"status": "ok", "provider": settings.email_provider})
            return
        self._json(404, {"error": "not found"})

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        query = parse_qs(parsed.query)
        if not self._authorized(query):
            self._json(401, {"error": "unauthorized"})
            return

        length = int(self.headers.get("Content-Length", 0) or 0)
        raw = self.rfile.read(length) if length else b""
        try:
            body = json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            body = {}

        if parsed.path == "/outreach/run":
            self._handle_outreach(body)
        elif parsed.path == "/esp/webhook":
            self._handle_esp_event(body)
        else:
            self._json(404, {"error": "not found"})

    # ------------------------------------------------------------------ #
    def _handle_outreach(self, body: dict) -> None:
        from fixgenie.pipeline import stage_outreach

        dry = bool(body.get("dry_run", False))
        try:
            stage_outreach(dry_run=dry)
            self._json(200, {"status": "outreach triggered", "dry_run": dry})
        except Exception as exc:  # keep the endpoint alive on errors
            log.exception("Outreach trigger failed")
            self._json(500, {"error": str(exc)})

    def _handle_esp_event(self, body: dict) -> None:
        """
        Normalize an ESP event and update the Sheet + suppression list.

        Brevo sends {"event": "unsubscribed"/"hard_bounce"/"opened"/..., "email": ...}.
        SendGrid sends a list of events. We handle both shapes minimally.
        """
        from fixgenie.outreach.compliance import SuppressionList

        events = body if isinstance(body, list) else [body]
        suppression = SuppressionList(settings.suppression_path)
        handled = 0
        for ev in events:
            email = (ev.get("email") or ev.get("recipient") or "").strip().lower()
            etype = (ev.get("event") or ev.get("event_type") or "").lower()
            if not email:
                continue
            if etype in ("unsubscribed", "unsubscribe", "spam", "complaint"):
                suppression.add(email, reason=etype)
            # Status updates (opened/replied/bounced) are mirrored to the Sheet
            # by the outreach/tracker job; logged here for the audit trail.
            log.info("ESP event: %s for %s", etype, email)
            handled += 1
        self._json(200, {"status": "ok", "events_handled": handled})


def main() -> None:
    port = int(os.environ.get("WEBHOOK_PORT", "8080"))
    if not _TOKEN:
        log.warning("WEBHOOK_TOKEN not set - endpoint is UNAUTHENTICATED. "
                    "Set it in .env before exposing this service.")
    server = ThreadingHTTPServer(("0.0.0.0", port), Handler)
    log.info("FixGenie webhook service listening on :%d", port)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.shutdown()


if __name__ == "__main__":
    main()
