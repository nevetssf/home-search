"""Zillow ingestion via the RapidAPI ``zillow-com1`` wrapper (PLAN.md §6).

Every raw response is returned to the caller so it can be cached in
``Property.raw_payload``; the app then reads from the DB and only re-hits the
API on explicit add or a scheduled refresh. ``ZillowUnavailable`` lets callers
fall back to manual entry pre-filled with whatever we got.

The wrapper is an unofficial scraper — keep it off the public internet
(PLAN.md §14). Field names below follow zillow-com1's documented shape; the
normalizer is defensive so partial/changed payloads degrade rather than crash.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import httpx

from ..config import settings


class ZillowUnavailable(RuntimeError):
    """No RapidAPI key configured, or the wrapper returned an error."""


@dataclass
class NormalizedListing:
    source_id: Optional[str]  # zpid
    source_url: Optional[str]
    address: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    zip: Optional[str] = None
    county: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    price: Optional[float] = None
    beds: Optional[float] = None
    baths: Optional[float] = None
    sqft: Optional[float] = None
    lot_size: Optional[float] = None
    year_built: Optional[int] = None
    property_type: Optional[str] = None
    status: str = "for_sale"
    days_on_market: Optional[int] = None
    description: Optional[str] = None
    photo_urls: List[str] = field(default_factory=list)
    raw: Dict[str, Any] = field(default_factory=dict)


# Zillow homeStatus → our internal status vocabulary.
_STATUS_MAP = {
    "FOR_SALE": "for_sale",
    "PENDING": "pending",
    "SOLD": "sold",
    "RECENTLY_SOLD": "sold",
    "OTHER": "off_market",
    "OFF_MARKET": "off_market",
    "COMING_SOON": "coming_soon",
}


def _to_float(v: Any) -> Optional[float]:
    try:
        return float(v) if v is not None and v != "" else None
    except (TypeError, ValueError):
        return None


def extract_zpid(url: str) -> Optional[str]:
    """Pull the zpid out of a Zillow URL like .../12345678_zpid/."""
    m = re.search(r"/(\d+)_zpid", url)
    return m.group(1) if m else None


def normalize(payload: Dict[str, Any]) -> NormalizedListing:
    """Map a zillow-com1 property payload onto our schema (defensive)."""
    addr = payload.get("address")
    if isinstance(addr, dict):
        street = addr.get("streetAddress")
        city = addr.get("city")
        state = addr.get("state")
        zipc = addr.get("zipcode")
    else:
        street = addr if isinstance(addr, str) else None
        city = payload.get("city")
        state = payload.get("state")
        zipc = payload.get("zipcode")

    photos: List[str] = []
    for p in payload.get("photos", []) or []:
        if isinstance(p, str):
            photos.append(p)
        elif isinstance(p, dict):
            url = p.get("url") or p.get("href")
            if url:
                photos.append(url)
    if not photos and payload.get("imgSrc"):
        photos.append(payload["imgSrc"])

    return NormalizedListing(
        source_id=str(payload.get("zpid")) if payload.get("zpid") else None,
        source_url=payload.get("url") or payload.get("hdpUrl"),
        address=street,
        city=city,
        state=state,
        zip=zipc,
        county=payload.get("county"),
        latitude=_to_float(payload.get("latitude")),
        longitude=_to_float(payload.get("longitude")),
        price=_to_float(payload.get("price")),
        beds=_to_float(payload.get("bedrooms")),
        baths=_to_float(payload.get("bathrooms")),
        sqft=_to_float(payload.get("livingArea") or payload.get("livingAreaValue")),
        lot_size=_to_float(payload.get("lotAreaValue")),
        year_built=int(payload["yearBuilt"]) if payload.get("yearBuilt") else None,
        property_type=payload.get("homeType") or payload.get("propertyTypeDimension"),
        status=_STATUS_MAP.get(str(payload.get("homeStatus", "")).upper(), "for_sale"),
        days_on_market=payload.get("daysOnZillow"),
        description=payload.get("description"),
        photo_urls=photos,
        raw=payload,
    )


class ZillowClient:
    def __init__(self, api_key: Optional[str] = None, host: Optional[str] = None):
        self.api_key = api_key if api_key is not None else settings.rapidapi_key
        self.host = host or settings.rapidapi_zillow_host

    def _headers(self) -> Dict[str, str]:
        if not self.api_key:
            raise ZillowUnavailable("RAPIDAPI_KEY is not configured")
        return {"X-RapidAPI-Key": self.api_key, "X-RapidAPI-Host": self.host}

    def _get(self, path: str, params: Dict[str, Any]) -> Dict[str, Any]:
        url = f"https://{self.host}{path}"
        with httpx.Client(timeout=30) as client:
            r = client.get(url, headers=self._headers(), params=params)
            if r.status_code >= 400:
                raise ZillowUnavailable(f"Zillow API {r.status_code}: {r.text[:200]}")
            return r.json()

    def fetch_by_url(self, listing_url: str) -> Dict[str, Any]:
        """Fetch a single property by its Zillow URL (or extracted zpid)."""
        zpid = extract_zpid(listing_url)
        params = {"zpid": zpid} if zpid else {"property_url": listing_url}
        return self._get("/property", params)

    def search(self, **filters: Any) -> List[Dict[str, Any]]:
        """Area search → list of property payloads (under 'props')."""
        payload = self._get("/propertyExtendedSearch", filters)
        return payload.get("props", []) or payload.get("results", []) or []
