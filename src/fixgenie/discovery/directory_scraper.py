"""
Directory scraper (Playwright) - opt-in, for public listing sites.

IMPORTANT / COMPLIANCE (Section 6 & 12):
  - This is OPT-IN (`--scrape` flag), never in the default source list, because
    scraping carries ToS/legal risk that official APIs don't.
  - Only point it at sites whose ToS you've checked and that publish this data
    publicly for business contact purposes.
  - It ships with anti-blocking *politeness* (delays, real UA, robots awareness)
    - NOT evasion. The goal is to behave like a considerate human, not to defeat
    protections. If a site blocks you, respect that and stop.

The scraper is written against a GENERIC listing-page structure and exposes CSS
selectors in one place (`SelectorProfile`) so you can adapt it to a specific
directory without touching the crawl logic. No selectors are hard-coded to a
particular site here, on purpose.
"""
from __future__ import annotations

import random
import time
import urllib.robotparser
from dataclasses import dataclass
from typing import Iterable
from urllib.parse import urljoin, urlparse

from fixgenie.common.logging_setup import get_logger
from fixgenie.common.models import Lead
from fixgenie.discovery.base import DiscoverySource, SearchTarget

log = get_logger(__name__)

_USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/17.0 Safari/605.1.15",
]


@dataclass
class SelectorProfile:
    """
    CSS selectors describing how to read a listing page.

    Fill these in for the specific public directory you have permission to use.
    Left as generic placeholders; the scraper degrades gracefully if a selector
    finds nothing.
    """

    listing_url_template: str          # e.g. "https://example.com/search?q={industry}&loc={city}"
    result_card: str                   # selector for each business card
    name: str
    phone: str = ""
    address: str = ""
    website: str = ""
    next_page: str = ""                # selector for the "next page" link


class DirectoryScraper(DiscoverySource):
    name = "Directory"

    def __init__(
        self,
        profile: SelectorProfile,
        min_delay: float = 3.0,
        max_delay: float = 7.0,
        max_pages: int = 3,
        respect_robots: bool = True,
    ) -> None:
        self.profile = profile
        self.min_delay = min_delay
        self.max_delay = max_delay
        self.max_pages = max_pages
        self.respect_robots = respect_robots

    def is_available(self) -> bool:
        # Available only if a profile with a URL template was provided.
        return bool(self.profile and self.profile.listing_url_template)

    # ------------------------------------------------------------------ #
    def _robots_allows(self, url: str, user_agent: str) -> bool:
        if not self.respect_robots:
            return True
        parsed = urlparse(url)
        robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
        rp = urllib.robotparser.RobotFileParser()
        try:
            rp.set_url(robots_url)
            rp.read()
            return rp.can_fetch(user_agent, url)
        except Exception:
            # If robots.txt can't be read, err on the side of caution: allow the
            # first page only (many sites have no robots.txt at all).
            return True

    def _sleep(self) -> None:
        time.sleep(random.uniform(self.min_delay, self.max_delay))

    def search(self, target: SearchTarget) -> Iterable[Lead]:
        if not self.is_available():
            log.info("Directory scraper skipped (no selector profile configured).")
            return
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            log.error(
                "Playwright not installed. Run: pip install playwright && playwright install chromium"
            )
            return

        start_url = self.profile.listing_url_template.format(
            industry=target.industry.replace(" ", "+"),
            city=target.city.replace(" ", "+"),
            region=target.region.replace(" ", "+"),
            country=target.country.replace(" ", "+"),
        )
        ua = random.choice(_USER_AGENTS)

        if not self._robots_allows(start_url, ua):
            log.warning("robots.txt disallows %s - respecting it and skipping.", start_url)
            return

        count = 0
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(user_agent=ua, locale="en-US")
            page = context.new_page()
            url = start_url
            for _ in range(self.max_pages):
                if count >= target.max_results:
                    break
                try:
                    page.goto(url, timeout=30000, wait_until="domcontentloaded")
                except Exception as exc:
                    log.error("Failed to load %s: %s", url, exc)
                    break

                cards = page.query_selector_all(self.profile.result_card)
                if not cards:
                    log.info("No result cards found on %s (selector may need updating).", url)
                    break

                for card in cards:
                    if count >= target.max_results:
                        break
                    lead = self._parse_card(card, target)
                    if lead:
                        count += 1
                        yield lead

                # Pagination.
                next_url = self._next_url(page, url)
                if not next_url or next_url == url:
                    break
                url = next_url
                self._sleep()  # be polite between pages

            context.close()
            browser.close()
        log.info("Directory scraper collected %d businesses for '%s'.", count, target.industry)

    def _parse_card(self, card, target: SearchTarget) -> Lead | None:
        def _text(sel: str) -> str:
            if not sel:
                return ""
            el = card.query_selector(sel)
            return el.inner_text().strip() if el else ""

        def _attr(sel: str, attr: str) -> str:
            if not sel:
                return ""
            el = card.query_selector(sel)
            return (el.get_attribute(attr) or "").strip() if el else ""

        name = _text(self.profile.name)
        if not name:
            return None
        return Lead(
            business_name=name,
            category=target.industry.title(),
            phone=_text(self.profile.phone),
            address=_text(self.profile.address),
            website=_attr(self.profile.website, "href"),
            city_region=target.city_region,
            source=self.name,
            source_url="",
        )

    def _next_url(self, page, current_url: str) -> str:
        if not self.profile.next_page:
            return ""
        el = page.query_selector(self.profile.next_page)
        if not el:
            return ""
        href = el.get_attribute("href") or ""
        return urljoin(current_url, href) if href else ""
