"""
Common interface every discovery source implements.

A "source" takes a SearchTarget (industry + location) and yields Lead objects
with the raw fields it could find (name, address, phone, website, category).
Enrichment/validation happen later - a source's only job is DISCOVERY.

This abstraction is what lets the pipeline treat Overpass, Google Places and the
directory scraper interchangeably and merge their results.
"""
from __future__ import annotations

import abc
from dataclasses import dataclass
from typing import Iterable

from fixgenie.common.models import Lead


@dataclass
class SearchTarget:
    """One (industry x location) job, parsed from campaigns.yaml."""

    industry: str
    city: str
    region: str = ""
    country: str = ""
    bbox: tuple[float, float, float, float] | None = None  # (south, west, north, east)
    max_results: int = 50

    @property
    def city_region(self) -> str:
        return ", ".join(p for p in (self.city, self.region) if p)

    @property
    def location_label(self) -> str:
        return ", ".join(p for p in (self.city, self.region, self.country) if p)

    @classmethod
    def from_dict(cls, d: dict) -> "SearchTarget":
        bbox = d.get("bbox")
        if isinstance(bbox, (list, tuple)) and len(bbox) == 4:
            bbox_t = tuple(float(x) for x in bbox)  # type: ignore[assignment]
        else:
            bbox_t = None
        return cls(
            industry=str(d.get("industry", "")).strip(),
            city=str(d.get("city", "")).strip(),
            region=str(d.get("region", "")).strip(),
            country=str(d.get("country", "")).strip(),
            bbox=bbox_t,  # type: ignore[arg-type]
            max_results=int(d.get("max_results", 50)),
        )


class DiscoverySource(abc.ABC):
    """Base class for all discovery sources."""

    #: Human-readable name written into the Lead.source field.
    name: str = "base"

    @abc.abstractmethod
    def is_available(self) -> bool:
        """Can this source run? (e.g. Google Places needs an API key.)"""

    @abc.abstractmethod
    def search(self, target: SearchTarget) -> Iterable[Lead]:
        """Yield Lead objects for the given target."""
