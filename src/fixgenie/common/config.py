"""
Central configuration loader.

Reads two things:
  1. Secrets/keys  -> from environment variables (.env file)
  2. Campaign setup -> from config/campaigns.yaml

Everything else in the codebase imports `settings` from here, so there is a
single source of truth and no secret is ever hard-coded.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv

# Project root = three levels up from this file (src/fixgenie/common/config.py)
PROJECT_ROOT = Path(__file__).resolve().parents[3]

# Load .env from the project root if present. Silent if it doesn't exist.
load_dotenv(PROJECT_ROOT / ".env")


def _env(key: str, default: str = "") -> str:
    """Fetch an env var, stripped. Returns default if unset/empty."""
    val = os.environ.get(key, "")
    return val.strip() if val and val.strip() else default


def _env_int(key: str, default: int) -> int:
    try:
        return int(_env(key, str(default)))
    except ValueError:
        return default


@dataclass
class Settings:
    """Runtime settings assembled from environment + YAML campaign file."""

    # --- Paths ---
    project_root: Path = PROJECT_ROOT
    data_dir: Path = PROJECT_ROOT / "data"
    staging_db_path: Path = PROJECT_ROOT / "data" / "staging.db"
    templates_dir: Path = PROJECT_ROOT / "templates"
    suppression_path: Path = PROJECT_ROOT / "data" / "suppression_list.txt"

    # --- Google Sheets ---
    google_service_account_json: str = field(
        default_factory=lambda: _env("GOOGLE_SERVICE_ACCOUNT_JSON", "./config/service_account.json")
    )
    google_sheet_name: str = field(
        default_factory=lambda: _env("GOOGLE_SHEET_NAME", "FixGenie Leads Master")
    )

    # --- Discovery ---
    overpass_endpoint: str = field(
        default_factory=lambda: _env("OVERPASS_ENDPOINT", "https://overpass-api.de/api/interpreter")
    )
    google_places_api_key: str = field(default_factory=lambda: _env("GOOGLE_PLACES_API_KEY"))

    # --- Enrichment ---
    hunter_api_key: str = field(default_factory=lambda: _env("HUNTER_API_KEY"))

    # --- LLM personalization (optional; Anthropic-Messages-format gateway) ---
    llm_base_url: str = field(default_factory=lambda: _env("LLM_BASE_URL"))
    llm_api_key: str = field(default_factory=lambda: _env("LLM_API_KEY"))
    llm_model: str = field(default_factory=lambda: _env("LLM_MODEL", "deepseek-v4-flash"))
    llm_user_agent: str = field(
        default_factory=lambda: _env("LLM_USER_AGENT", "claude-cli/1.0.60 (external)")
    )

    # --- Email sending ---
    email_provider: str = field(default_factory=lambda: _env("EMAIL_PROVIDER", "gmail").lower())
    gmail_address: str = field(default_factory=lambda: _env("GMAIL_ADDRESS"))
    gmail_app_password: str = field(default_factory=lambda: _env("GMAIL_APP_PASSWORD"))
    brevo_api_key: str = field(default_factory=lambda: _env("BREVO_API_KEY"))

    # --- Sender identity (legally required footer fields) ---
    sender_name: str = field(default_factory=lambda: _env("SENDER_NAME", "FixGenie Team"))
    sender_company: str = field(default_factory=lambda: _env("SENDER_COMPANY", "FixGenie Consulting Inc"))
    sender_email: str = field(default_factory=lambda: _env("SENDER_EMAIL", "hello@fixgenie.co"))
    sender_postal_address: str = field(
        default_factory=lambda: _env("SENDER_POSTAL_ADDRESS", "Address not set")
    )
    unsubscribe_base_url: str = field(
        default_factory=lambda: _env("UNSUBSCRIBE_BASE_URL", "https://fixgenie.co/unsubscribe")
    )

    # --- Meeting booking CTA (Google Calendar appointment page, Calendly, etc.) ---
    # If set, every email shows a one-click "book a call" button/link so the
    # recipient can grab a slot without replying. Leave empty to hide it.
    booking_url: str = field(default_factory=lambda: _env("BOOKING_URL"))
    booking_cta: str = field(
        default_factory=lambda: _env("BOOKING_CTA", "Book a 15-min call")
    )

    # --- Safety limits ---
    daily_send_limit: int = field(default_factory=lambda: _env_int("DAILY_SEND_LIMIT", 40))
    send_delay_seconds: int = field(default_factory=lambda: _env_int("SEND_DELAY_SECONDS", 45))

    # --- Campaign YAML (loaded lazily) ---
    _campaigns: dict[str, Any] | None = None

    @property
    def campaigns(self) -> dict[str, Any]:
        """Parsed contents of config/campaigns.yaml (cached)."""
        if self._campaigns is None:
            path = self.project_root / "config" / "campaigns.yaml"
            if path.exists():
                with open(path, "r", encoding="utf-8") as fh:
                    self._campaigns = yaml.safe_load(fh) or {}
            else:
                self._campaigns = {}
        return self._campaigns

    # --- Convenience flags ---
    @property
    def has_google_places(self) -> bool:
        return bool(self.google_places_api_key)

    @property
    def has_hunter(self) -> bool:
        return bool(self.hunter_api_key)

    @property
    def has_llm(self) -> bool:
        return bool(self.llm_base_url and self.llm_api_key)

    @property
    def has_booking(self) -> bool:
        return bool(self.booking_url)

    def resolve_path(self, maybe_relative: str) -> Path:
        """Resolve a path that may be relative to the project root."""
        p = Path(maybe_relative)
        return p if p.is_absolute() else (self.project_root / p)

    def ensure_dirs(self) -> None:
        """Create data dir and cache dir if missing."""
        self.data_dir.mkdir(parents=True, exist_ok=True)
        (self.data_dir / "raw_html_cache").mkdir(parents=True, exist_ok=True)


# Singleton imported everywhere: `from fixgenie.common.config import settings`
settings = Settings()
