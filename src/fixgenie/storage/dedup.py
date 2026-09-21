"""
De-duplication (Section 8: pandas + rapidfuzz).

Two layers:
  1. Exact: the deterministic Lead.lead_id (name+city+phone hash) already blocks
     re-discovery of the identical business.
  2. Fuzzy: catches "Joe's Plumbing" vs "Joes Plumbing Inc" in the same city, or
     rows sharing a phone/email/website domain, which the hash would miss.

Used before pushing to Sheets: new leads are matched against BOTH the existing
Sheet rows and each other, so we only ever append genuinely new businesses.
"""
from __future__ import annotations

from fixgenie.common.logging_setup import get_logger
from fixgenie.common.models import Lead

log = get_logger(__name__)


def _token_sort_ratio(a: str, b: str) -> float:
    """
    Similarity score 0-100, token-order-independent.

    Uses rapidfuzz when available (fast, C-backed). Falls back to the stdlib
    difflib so the pipeline still de-dups correctly even if rapidfuzz isn't
    installed — just a little slower.
    """
    a_sorted = " ".join(sorted(a.split()))
    b_sorted = " ".join(sorted(b.split()))
    try:
        from rapidfuzz import fuzz

        return fuzz.ratio(a_sorted, b_sorted)
    except Exception:
        from difflib import SequenceMatcher

        return SequenceMatcher(None, a_sorted, b_sorted).ratio() * 100.0


def _norm_name(name: str) -> str:
    """Strip legal suffixes/punctuation so fuzzy matching focuses on the core name."""
    n = name.lower()
    for suffix in (" inc", " llc", " ltd", " co", " corp", " company", " limited", "."):
        n = n.replace(suffix, " ")
    return " ".join(n.split())


def _digits(s: str) -> str:
    return "".join(ch for ch in s if ch.isdigit())


def is_duplicate(candidate: Lead, existing: Lead, name_threshold: int = 88) -> bool:
    """True if candidate and existing are very likely the same business."""
    # Strong signals: shared phone, email, or website domain.
    if candidate.phone and existing.phone and _digits(candidate.phone) == _digits(existing.phone):
        return True
    if candidate.email and existing.email and candidate.email.lower() == existing.email.lower():
        return True
    if candidate.domain and existing.domain and candidate.domain == existing.domain:
        return True

    # Fuzzy name match, but only if plausibly the same locale.
    same_city = _norm_name(candidate.city_region) == _norm_name(existing.city_region)
    if same_city or not (candidate.city_region and existing.city_region):
        score = _token_sort_ratio(
            _norm_name(candidate.business_name), _norm_name(existing.business_name)
        )
        if score >= name_threshold:
            return True
    return False


def filter_new_leads(
    candidates: list[Lead],
    existing: list[Lead],
    name_threshold: int = 88,
) -> tuple[list[Lead], int]:
    """
    Return (new_leads, num_duplicates_dropped).

    Dedups candidates against `existing` (e.g. current Sheet rows) AND against
    each other, so a single batch can't introduce internal duplicates.
    """
    kept: list[Lead] = []
    dropped = 0
    pool = list(existing)  # grows as we accept candidates

    for cand in candidates:
        if any(is_duplicate(cand, e, name_threshold) for e in pool):
            dropped += 1
            continue
        kept.append(cand)
        pool.append(cand)

    log.info("Dedup: kept %d new, dropped %d duplicates.", len(kept), dropped)
    return kept, dropped
