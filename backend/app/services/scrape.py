"""Best-effort direct scrapers for Zillow & Redfin listing URLs (PLAN.md §6).

No headless browser (protects the N5105's RAM, PLAN.md §9): a single ``httpx``
GET with a browser-like User-Agent, then we parse the structured data the page
already ships:

* **JSON-LD** (``<script type="application/ld+json">``) — schema.org data both
  sites embed. Stable across redesigns; reliably yields address, geo, price,
  and photos. This is the common baseline for both sites.
* **Zillow ``__NEXT_DATA__``** — the richer Next.js cache (beds/baths/sqft/
  status/description). Brittle, so it's a bonus layered on top of JSON-LD.

Raises ``ScrapeBlocked`` when the page can't be fetched/parsed (e.g. Zillow's
bot wall from a datacenter IP) so callers can fall back to the RapidAPI wrapper
or to manual entry. Direct scraping is most reliable from a residential IP.
"""
from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional

import httpx

from .zillow import NormalizedListing, _STATUS_MAP, _to_float

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
_HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

_JSONLD_RE = re.compile(
    r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
    re.DOTALL | re.IGNORECASE,
)
_NEXT_DATA_RE = re.compile(
    r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>',
    re.DOTALL,
)


class ScrapeBlocked(RuntimeError):
    """The page could not be fetched or yielded no parseable listing data."""


def fetch_html(url: str) -> str:
    try:
        with httpx.Client(timeout=25, follow_redirects=True, headers=_HEADERS) as c:
            r = c.get(url)
    except httpx.HTTPError as e:
        raise ScrapeBlocked(f"request failed: {e}")
    if r.status_code >= 400:
        raise ScrapeBlocked(f"HTTP {r.status_code} (likely bot-blocked)")
    text = r.text
    # Heuristic bot-wall detection.
    if "px-captcha" in text or "Please verify you're a human" in text:
        raise ScrapeBlocked("bot challenge served")
    return text


# ── JSON-LD (common to both sites) ───────────────────────────────────────────
_LISTING_TYPES = {
    "singlefamilyresidence", "house", "residence", "place", "product",
    "apartment", "realestatelisting", "offer",
}


def _iter_jsonld(html: str):
    for block in _JSONLD_RE.findall(html):
        try:
            data = json.loads(block)
        except json.JSONDecodeError:
            continue
        # A block may be a single object, a list, or use @graph.
        items = data if isinstance(data, list) else data.get("@graph", [data]) \
            if isinstance(data, dict) else []
        for item in items:
            if isinstance(item, dict):
                yield item


def parse_jsonld(html: str) -> Dict[str, Any]:
    """Merge schema.org listing fields from any JSON-LD blocks on the page."""
    out: Dict[str, Any] = {}
    photos: List[str] = []
    for item in _iter_jsonld(html):
        t = item.get("@type", "")
        types = [t] if isinstance(t, str) else (t or [])
        if not any(str(x).lower() in _LISTING_TYPES for x in types):
            # still mine offers/images if address present
            if "address" not in item and "image" not in item:
                continue
        addr = item.get("address")
        if isinstance(addr, dict):
            out.setdefault("street", addr.get("streetAddress"))
            out.setdefault("city", addr.get("addressLocality"))
            out.setdefault("state", addr.get("addressRegion"))
            out.setdefault("zip", addr.get("postalCode"))
        geo = item.get("geo")
        if isinstance(geo, dict):
            out.setdefault("latitude", _to_float(geo.get("latitude")))
            out.setdefault("longitude", _to_float(geo.get("longitude")))
        offers = item.get("offers")
        if isinstance(offers, dict):
            out.setdefault("price", _to_float(offers.get("price")))
        if item.get("numberOfBedrooms") is not None:
            out.setdefault("beds", _to_float(item.get("numberOfBedrooms")))
        if item.get("numberOfBathroomsTotal") is not None:
            out.setdefault("baths", _to_float(item.get("numberOfBathroomsTotal")))
        img = item.get("image")
        if isinstance(img, str):
            photos.append(img)
        elif isinstance(img, list):
            photos.extend(x for x in img if isinstance(x, str))
        out.setdefault("description", item.get("description"))
    if photos:
        out["photos"] = list(dict.fromkeys(photos))  # de-dup, preserve order
    return out


def _jsonld_to_listing(url: str, ld: Dict[str, Any], source_id: Optional[str]) -> NormalizedListing:
    return NormalizedListing(
        source_id=source_id,
        source_url=url,
        address=ld.get("street"),
        city=ld.get("city"),
        state=ld.get("state"),
        zip=ld.get("zip"),
        latitude=ld.get("latitude"),
        longitude=ld.get("longitude"),
        price=ld.get("price"),
        beds=ld.get("beds"),
        baths=ld.get("baths"),
        description=ld.get("description"),
        photo_urls=ld.get("photos", []),
        raw={"_scraped": "jsonld", "jsonld": ld, "url": url},
    )


# ── Zillow ───────────────────────────────────────────────────────────────────
def _zillow_next_data_property(html: str) -> Optional[Dict[str, Any]]:
    m = _NEXT_DATA_RE.search(html)
    if not m:
        return None
    try:
        data = json.loads(m.group(1))
        cache = data["props"]["pageProps"]["componentProps"]["gdpClientCache"]
        cache = json.loads(cache) if isinstance(cache, str) else cache
    except (KeyError, TypeError, json.JSONDecodeError):
        return None
    for v in cache.values():
        if isinstance(v, dict) and isinstance(v.get("property"), dict):
            return v["property"]
    return None


def scrape_zillow(url: str) -> NormalizedListing:
    """Direct-fetch a Zillow listing. Prefers __NEXT_DATA__, falls back to JSON-LD."""
    from .zillow import extract_zpid, normalize

    html = fetch_html(url)
    prop = _zillow_next_data_property(html)
    if prop:
        listing = normalize(prop)
        listing.source_url = listing.source_url or url
        listing.raw = {"_scraped": "next_data", **prop}
        return listing
    ld = parse_jsonld(html)
    if ld.get("street") or ld.get("price") or ld.get("latitude"):
        return _jsonld_to_listing(url, ld, extract_zpid(url))
    raise ScrapeBlocked("no listing data found in Zillow page")


# ── Redfin ───────────────────────────────────────────────────────────────────
def _redfin_status(html: str) -> str:
    # Cheap status sniff from the page; defaults to for_sale.
    lowered = html.lower()
    for needle, status in (
        ("\"pending\"", "pending"), ("contingent", "pending"),
        ("\"sold\"", "sold"), ("recently sold", "sold"),
        ("coming soon", "coming_soon"),
    ):
        if needle in lowered:
            return status
    return "for_sale"


def _redfin_listing_id(url: str) -> Optional[str]:
    m = re.search(r"/home/(\d+)", url)
    return m.group(1) if m else None


def scrape_redfin(url: str) -> NormalizedListing:
    """Direct-fetch a Redfin listing via its embedded JSON-LD structured data."""
    html = fetch_html(url)
    ld = parse_jsonld(html)
    if not (ld.get("street") or ld.get("price") or ld.get("latitude")):
        raise ScrapeBlocked("no listing data found in Redfin page")
    listing = _jsonld_to_listing(url, ld, _redfin_listing_id(url))
    listing.status = _STATUS_MAP.get(_redfin_status(html).upper(), _redfin_status(html))
    return listing


# ── Dispatch by hostname ─────────────────────────────────────────────────────
def detect_source(url: str) -> Optional[str]:
    u = url.lower()
    if "zillow.com" in u:
        return "zillow"
    if "redfin.com" in u:
        return "redfin"
    return None
