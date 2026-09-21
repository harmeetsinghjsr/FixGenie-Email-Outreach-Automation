"""
Google Places API discovery source (optional booster).

Runs ONLY if GOOGLE_PLACES_API_KEY is set. Google gives a recurring free credit
(~$200/month) which covers a few thousand lookups - plenty for the Bootstrap
phase. This is the lowest-legal-risk paid-ish source because it's an official
API, not scraping (Section 6 / Section 12).

Uses the Places API "Text Search" (new v1 endpoint) then reads the fields we
need directly from the response (no separate Details call needed for the basics).
"""
from __future__ import annotations

import time
from typing import Iterable

import requests

from fixgenie.common.logging_setup import get_logger
from fixgenie.common.models import Lead
from fixgenie.discovery.base import DiscoverySource, SearchTarget

log = get_logger(__name__)

_TEXT_SEARCH_URL = "https://places.googleapis.com/v1/places:searchText"

# Which fields to ask Google for. Keeping this tight controls cost (billed per
# field group). These cover Section 3's raw fields.
_FIELD_MASK = ",".join(
    [
        "places.displayName",
        "places.formattedAddress",
        "places.nationalPhoneNumber",
        "places.internationalPhoneNumber",
        "places.websiteUri",
        "places.primaryType",
        "places.googleMapsUri",
    ]
)


class GooglePlacesSource(DiscoverySource):
    name = "Google Places"

    def __init__(self, api_key: str, polite_delay: float = 2.0) -> None:
        self.api_key = api_key
        self.polite_delay = polite_delay
        self._session = requests.Session()

    def is_available(self) -> bool:
        return bool(self.api_key)

    def search(self, target: SearchTarget) -> Iterable[Lead]:
        if not self.is_available():
            log.info("Google Places skipped (no API key).")
            return

        headers = {
            "Content-Type": "application/json",
            "X-Goog-Api-Key": self.api_key,
            "X-Goog-FieldMask": _FIELD_MASK + ",nextPageToken",
        }
        query = f"{target.industry} in {target.location_label}"
        body: dict = {"textQuery": query, "pageSize": min(target.max_results, 20)}

        fetched = 0
        page_token: str | None = None
        while fetched < target.max_results:
            if page_token:
                body["pageToken"] = page_token
            try:
                resp = self._session.post(
                    _TEXT_SEARCH_URL, headers=headers, json=body, timeout=20
                )
                resp.raise_for_status()
                data = resp.json()
            except (requests.RequestException, ValueError) as exc:
                log.error("Google Places request failed: %s", exc)
                return

            places = data.get("places", [])
            if not places:
                break

            for place in places:
                lead = self._parse_place(place, target)
                if lead:
                    fetched += 1
                    yield lead
                    if fetched >= target.max_results:
                        break

            page_token = data.get("nextPageToken")
            if not page_token:
                break
            time.sleep(self.polite_delay)  # token needs a moment to activate

        log.info("Google Places returned %d businesses for '%s'.", fetched, target.industry)

    def _parse_place(self, place: dict, target: SearchTarget) -> Lead | None:
        name = (place.get("displayName", {}) or {}).get("text", "").strip()
        if not name:
            return None
        phone = (
            place.get("internationalPhoneNumber")
            or place.get("nationalPhoneNumber")
            or ""
        ).strip()
        return Lead(
            business_name=name,
            category=(place.get("primaryType") or target.industry).replace("_", " ").title(),
            phone=phone,
            website=(place.get("websiteUri") or "").strip(),
            address=(place.get("formattedAddress") or "").strip(),
            city_region=target.city_region,
            source=self.name,
            source_url=(place.get("googleMapsUri") or "").strip(),
        )
