"""
OpenStreetMap Overpass discovery source  ---  the free, unlimited, legal core.

Why this is the primary source:
  - 100% free, no API key, no credit card. Ever.
  - Legal: OSM data is open (ODbL license). We're querying published business
    POIs, not scraping a site that forbids it.
  - Rich for local businesses: name, address, phone, website, and category tags
    are exactly the fields Section 3 asks for.

How it works:
  1. Geocode the city -> bounding box via Nominatim (also free OSM service).
  2. Build an Overpass QL query for nodes/ways tagged with the industry
     (mapped to OSM tags like shop=hairdresser, amenity=restaurant, craft=plumber).
  3. Parse the JSON into Lead objects.

Be a good citizen (Section 12): send a real User-Agent, add polite delays,
and cache geocoding. Overpass and Nominatim both ask for this.
"""
from __future__ import annotations

import time
from typing import Iterable

import requests

from fixgenie.common.logging_setup import get_logger
from fixgenie.common.models import Lead
from fixgenie.discovery.base import DiscoverySource, SearchTarget

log = get_logger(__name__)

_USER_AGENT = "FixGenie-Outreach/1.0 (contact: hello@fixgenie.co)"
_NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"

# Map common industry keywords -> OSM tag filters. Extend freely.
# Each value is a list of (key, value) tag pairs; ANY match includes the POI.
_INDUSTRY_TAGS: dict[str, list[tuple[str, str]]] = {
    "plumber": [("craft", "plumber"), ("shop", "trade"), ("office", "company")],
    "electrician": [("craft", "electrician")],
    "hair salon": [("shop", "hairdresser"), ("shop", "beauty")],
    "salon": [("shop", "hairdresser"), ("shop", "beauty")],
    "restaurant": [("amenity", "restaurant")],
    "cafe": [("amenity", "cafe")],
    "dentist": [("amenity", "dentist"), ("healthcare", "dentist")],
    "lawyer": [("office", "lawyer")],
    "accountant": [("office", "accountant"), ("office", "tax_advisor")],
    "real estate": [("office", "estate_agent")],
    "gym": [("leisure", "fitness_centre")],
    "auto repair": [("shop", "car_repair")],
    "roofer": [("craft", "roofer")],
    "landscaper": [("craft", "gardener"), ("shop", "garden_centre")],
    "cleaning": [("shop", "laundry"), ("craft", "cleaning")],
}


class OverpassSource(DiscoverySource):
    name = "OpenStreetMap"

    def __init__(self, endpoint: str, polite_delay: float = 2.0) -> None:
        self.endpoint = endpoint
        self.polite_delay = polite_delay
        self._session = requests.Session()
        self._session.headers.update({"User-Agent": _USER_AGENT})

    def is_available(self) -> bool:
        return True  # always free, always on

    # ------------------------------------------------------------------ #
    def _tag_filters(self, industry: str) -> list[tuple[str, str]]:
        key = industry.strip().lower()
        if key in _INDUSTRY_TAGS:
            return _INDUSTRY_TAGS[key]
        # Fallback: search the name field for the keyword across shops/offices.
        log.info("No OSM tag mapping for '%s' - falling back to name search.", industry)
        return []

    def _geocode_bbox(
        self, target: SearchTarget
    ) -> tuple[float, float, float, float] | None:
        """Resolve a city name to (south, west, north, east) via Nominatim."""
        if target.bbox:
            return target.bbox
        params = {
            "q": target.location_label,
            "format": "json",
            "limit": 1,
        }
        try:
            resp = self._session.get(_NOMINATIM_URL, params=params, timeout=15)
            resp.raise_for_status()
            data = resp.json()
        except (requests.RequestException, ValueError) as exc:
            log.error("Nominatim geocoding failed for '%s': %s", target.location_label, exc)
            return None
        if not data:
            log.warning("Nominatim returned no match for '%s'.", target.location_label)
            return None
        # Nominatim boundingbox = [south, north, west, east] as strings.
        bb = data[0].get("boundingbox")
        if not bb or len(bb) != 4:
            return None
        south, north, west, east = (float(x) for x in bb)
        time.sleep(1.0)  # Nominatim asks for <=1 request/sec
        return (south, west, north, east)

    def _build_query(
        self, target: SearchTarget, bbox: tuple[float, float, float, float]
    ) -> str:
        south, west, north, east = bbox
        bbox_str = f"{south},{west},{north},{east}"
        filters = self._tag_filters(target.industry)

        clauses: list[str] = []
        if filters:
            for k, v in filters:
                for elem in ("node", "way"):
                    clauses.append(f'{elem}["{k}"="{v}"]["name"]({bbox_str});')
        else:
            # Name-based fallback: case-insensitive regex on the name tag.
            kw = target.industry.replace('"', "")
            for elem in ("node", "way"):
                clauses.append(f'{elem}["name"~"{kw}",i]["shop"]({bbox_str});')
                clauses.append(f'{elem}["name"~"{kw}",i]["office"]({bbox_str});')

        body = "\n  ".join(clauses)
        # 'out center' gives a lat/lon even for ways (polygons).
        return f"[out:json][timeout:60];\n(\n  {body}\n);\nout center {target.max_results};"

    def _parse_element(self, el: dict, target: SearchTarget) -> Lead | None:
        tags = el.get("tags", {})
        name = tags.get("name", "").strip()
        if not name:
            return None

        # Assemble address from OSM addr:* tags.
        addr_parts = [
            tags.get("addr:housenumber", ""),
            tags.get("addr:street", ""),
            tags.get("addr:city", target.city),
            tags.get("addr:state", target.region),
            tags.get("addr:postcode", ""),
            target.country,
        ]
        address = ", ".join(p for p in addr_parts if p).strip(", ")

        website = (
            tags.get("website")
            or tags.get("contact:website")
            or tags.get("url", "")
        ).strip()
        phone = (tags.get("phone") or tags.get("contact:phone", "")).strip()
        email = (tags.get("email") or tags.get("contact:email", "")).strip()

        # Build the source URL back to the OSM object for auditability.
        osm_type = el.get("type", "node")
        osm_id = el.get("id", "")
        source_url = f"https://www.openstreetmap.org/{osm_type}/{osm_id}"

        return Lead(
            business_name=name,
            category=target.industry.title(),
            email=email,
            phone=phone,
            website=website,
            address=address,
            city_region=target.city_region,
            source=self.name,
            source_url=source_url,
        )

    # ------------------------------------------------------------------ #
    def search(self, target: SearchTarget) -> Iterable[Lead]:
        bbox = self._geocode_bbox(target)
        if not bbox:
            log.error("Could not resolve a bounding box for %s; skipping Overpass.",
                      target.location_label)
            return
        query = self._build_query(target, bbox)
        log.info("Overpass search: %s in %s", target.industry, target.location_label)

        try:
            resp = self._session.post(self.endpoint, data={"data": query}, timeout=90)
            resp.raise_for_status()
            payload = resp.json()
        except (requests.RequestException, ValueError) as exc:
            log.error("Overpass query failed: %s", exc)
            return

        elements = payload.get("elements", [])
        seen_names: set[str] = set()
        count = 0
        for el in elements:
            lead = self._parse_element(el, target)
            if lead is None:
                continue
            # Cheap in-batch dedup on name to avoid node+way duplicates.
            key = lead.business_name.lower()
            if key in seen_names:
                continue
            seen_names.add(key)
            count += 1
            yield lead
            if count >= target.max_results:
                break
        log.info("Overpass returned %d businesses for '%s'.", count, target.industry)
        time.sleep(self.polite_delay)
