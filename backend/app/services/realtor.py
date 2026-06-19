"""Realtor.com ingestion via the HomeHarvest library (PLAN.md §6).

A third listing source alongside Zillow and Redfin. HomeHarvest queries
Realtor.com's internal API over plain HTTP — **no headless browser** — so it
respects the boulder-server RAM budget (PLAN.md §9). No API key is required.

Like the Zillow wrapper it is an unofficial scraper: keep it off the public
internet (PLAN.md §14), and ``RealtorUnavailable`` lets callers degrade to
manual entry. HomeHarvest is *search/area* oriented (no single-listing-by-URL
fetch), so this module exposes ``search`` only.

Every result is normalized onto the shared :class:`NormalizedListing` and its
full payload retained in ``raw`` so it caches into ``Property.raw_payload`` the
same way every other source does.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from ..config import settings
from .zillow import NormalizedListing, _to_float


class RealtorUnavailable(RuntimeError):
    """Realtor ingestion is disabled, or HomeHarvest returned/raised an error."""


# HomeHarvest status strings → our internal status vocabulary.
_STATUS_MAP = {
    "FOR_SALE": "for_sale",
    "FOR_RENT": "for_sale",  # we only ever request for_sale; map defensively
    "PENDING": "pending",
    "CONTINGENT": "pending",
    "SOLD": "sold",
    "OFF_MARKET": "off_market",
    "READY_TO_BUILD": "coming_soon",  # new construction not yet listed
    "COMING_SOON": "coming_soon",
}

# HomeHarvest listing_type values (lowercase) that map onto our request surface.
VALID_LISTING_TYPES = ("for_sale", "for_rent", "sold", "pending")


def _photo_urls(desc: Any) -> List[str]:
    """Collect promo photo URLs from a HomeHarvest Description (HttpUrl → str)."""
    urls: List[str] = []
    if desc is None:
        return urls
    if getattr(desc, "primary_photo", None):
        urls.append(str(desc.primary_photo))
    for p in getattr(desc, "alt_photos", None) or []:
        urls.append(str(p))
    return list(dict.fromkeys(urls))  # de-dup, preserve order


def _baths(desc: Any) -> Optional[float]:
    """Combine full + half baths into a single count (half == 0.5)."""
    if desc is None:
        return None
    full = getattr(desc, "baths_full", None)
    half = getattr(desc, "baths_half", None)
    if full is None and half is None:
        return None
    return (full or 0) + (half or 0) * 0.5


def normalize(prop: Any) -> NormalizedListing:
    """Map a HomeHarvest ``Property`` model onto our schema (defensive)."""
    addr = getattr(prop, "address", None)
    desc = getattr(prop, "description", None)

    return NormalizedListing(
        source_id=str(prop.property_id) if getattr(prop, "property_id", None) else None,
        source_url=str(prop.property_url) if getattr(prop, "property_url", None) else None,
        address=getattr(addr, "full_line", None) or getattr(addr, "street", None),
        city=getattr(addr, "city", None),
        state=getattr(addr, "state", None),
        zip=getattr(addr, "zip", None),
        county=getattr(prop, "county", None),
        latitude=_to_float(getattr(prop, "latitude", None)),
        longitude=_to_float(getattr(prop, "longitude", None)),
        price=_to_float(getattr(prop, "list_price", None)),
        beds=_to_float(getattr(desc, "beds", None)),
        baths=_baths(desc),
        sqft=_to_float(getattr(desc, "sqft", None)),
        lot_size=_to_float(getattr(desc, "lot_sqft", None)),
        year_built=int(desc.year_built) if getattr(desc, "year_built", None) else None,
        property_type=getattr(desc, "style", None) or getattr(desc, "type", None),
        status=_STATUS_MAP.get(str(getattr(prop, "status", "") or "").upper(), "for_sale"),
        days_on_market=getattr(prop, "days_on_mls", None),
        description=getattr(desc, "text", None),
        photo_urls=_photo_urls(desc),
        raw=_dump(prop),
    )


def _dump(prop: Any) -> Dict[str, Any]:
    """JSON-safe dict of the model for ``Property.raw_payload`` (HttpUrl/dates)."""
    try:
        return prop.model_dump(mode="json")
    except Exception:
        return {"_source": "realtor", "property_id": getattr(prop, "property_id", None)}


def search(
    location: str,
    listing_type: str = "for_sale",
    *,
    radius: Optional[float] = None,
    beds_min: Optional[int] = None,
    baths_min: Optional[float] = None,
    price_min: Optional[int] = None,
    price_max: Optional[int] = None,
    sqft_min: Optional[int] = None,
    sqft_max: Optional[int] = None,
    past_days: Optional[int] = None,
    limit: int = 200,
) -> List[NormalizedListing]:
    """Area/criteria search on Realtor.com → normalized listings.

    Wraps :func:`homeharvest.scrape_property`; any library error (network,
    parse, bad input) is surfaced as :class:`RealtorUnavailable` so callers can
    fall back to manual entry.
    """
    if not settings.realtor_enabled:
        raise RealtorUnavailable("Realtor ingestion is disabled (REALTOR_ENABLED=false)")
    if listing_type not in VALID_LISTING_TYPES:
        raise RealtorUnavailable(f"invalid listing_type: {listing_type!r}")

    # Import lazily so the rest of the app (and tests) don't pay the
    # pandas/numpy import cost unless Realtor ingestion is actually used.
    try:
        from homeharvest import scrape_property
    except ImportError as e:  # pragma: no cover - dependency missing
        raise RealtorUnavailable(f"homeharvest not installed: {e}")

    eff_radius = radius if radius is not None else (settings.realtor_default_radius or None)
    kwargs: Dict[str, Any] = {
        "location": location,
        "listing_type": listing_type,
        "return_type": "pydantic",
        "limit": limit,
    }
    for key, val in (
        ("radius", eff_radius),
        ("beds_min", beds_min),
        ("baths_min", baths_min),
        ("price_min", price_min),
        ("price_max", price_max),
        ("sqft_min", sqft_min),
        ("sqft_max", sqft_max),
        ("past_days", past_days),
    ):
        if val:
            kwargs[key] = val

    try:
        results = scrape_property(**kwargs)
    except Exception as e:  # HomeHarvest raises various exceptions on failure
        raise RealtorUnavailable(f"Realtor search failed: {e}")

    return [normalize(p) for p in (results or [])]
