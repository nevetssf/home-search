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
from urllib.parse import urlparse

import httpx

from .zillow import NormalizedListing, _to_float

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


def _collect_image_urls(val) -> List[str]:
    """Pull image URLs from a schema.org ``image`` value (str / ImageObject /
    list of either)."""
    out: List[str] = []
    if isinstance(val, str):
        out.append(val)
    elif isinstance(val, dict):
        if val.get("url"):
            out.append(val["url"])
    elif isinstance(val, list):
        for x in val:
            out.extend(_collect_image_urls(x))
    return out


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
        photos.extend(_collect_image_urls(item.get("image")))
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


# Zillow bot-walls direct fetches, so we also support reconstructing the address
# straight from the URL slug (which is reliable) — used as a no-API fallback.
_ZPID_SLUG_RE = re.compile(r"/homedetails/([^/]+)/(\d+)_zpid")
_nomi = None  # cached pgeocode Nominatim


def _zip_lookup(zipc: Optional[str]) -> Optional[Dict[str, Any]]:
    """Resolve a US ZIP to city/state/centroid via pgeocode (offline). Returns
    None if pgeocode is unavailable or the ZIP is unknown."""
    if not zipc:
        return None
    global _nomi
    try:
        import math
        import pgeocode
    except ImportError:  # pragma: no cover - optional dependency
        return None
    if _nomi is None:
        _nomi = pgeocode.Nominatim("us")
    try:
        rec = _nomi.query_postal_code(zipc)
    except Exception:
        return None

    def _clean(v):
        if v is None:
            return None
        if isinstance(v, float) and math.isnan(v):
            return None
        return v

    place = _clean(getattr(rec, "place_name", None))
    if place is None:
        return None
    lat = _clean(getattr(rec, "latitude", None))
    lng = _clean(getattr(rec, "longitude", None))
    state = _clean(getattr(rec, "state_code", None))
    return {
        "city": place,
        "state": state if isinstance(state, str) else None,
        "lat": float(lat) if lat is not None else None,
        "lng": float(lng) if lng is not None else None,
    }


def parse_zillow_url(url: str) -> Optional[Dict[str, Any]]:
    """Reconstruct address fields from a Zillow ``/homedetails/<slug>/<zpid>_zpid``
    URL. The slug encodes ``<street>-<City Words>-<ST>-<zip>`` but doesn't delimit
    street vs city, so we take ZIP+state from the slug and resolve the (possibly
    multi-word) city + centroid from the ZIP, then strip the city words off the
    tail to recover the street. Returns None if the URL isn't a listing URL."""
    m = _ZPID_SLUG_RE.search(url)
    if not m:
        return None
    slug, zpid = m.group(1), m.group(2)
    tokens = [t for t in slug.split("-") if t]

    zipc = state = None
    if tokens and re.fullmatch(r"\d{5}", tokens[-1]):
        zipc = tokens.pop()
    if tokens and re.fullmatch(r"[A-Za-z]{2}", tokens[-1]):
        state = tokens.pop().upper()

    city = lat = lng = None
    info = _zip_lookup(zipc)
    if info:
        city = info["city"]
        state = state or info["state"]
        lat, lng = info["lat"], info["lng"]
        # Strip the (resolved) city words off the tail to leave just the street.
        ct = [w.lower() for w in city.split()]
        n = len(ct)
        if n and len(tokens) >= n and [t.lower() for t in tokens[-n:]] == ct:
            tokens = tokens[:-n]

    return {
        "zpid": zpid,
        "street": " ".join(tokens) if tokens else None,
        "city": city,
        "state": state,
        "zip": zipc,
        "lat": lat,
        "lng": lng,
    }


# ── Redfin ───────────────────────────────────────────────────────────────────
# A Redfin listing page embeds MANY JSON-LD blocks: the subject is the single
# `RealEstateListing`, while the `SingleFamilyResidence` blocks are the
# "similar homes" sidebar (a different address!). We must target the subject
# block and never merge the sidebar in — that merge was the Santa-Rosa→SF bug.
def _redfin_listing_id(url: str) -> Optional[str]:
    m = re.search(r"/home/(\d+)", url)
    return m.group(1) if m else None


def _find_realestate_listing(html: str) -> Optional[Dict[str, Any]]:
    for item in _iter_jsonld(html):
        t = item.get("@type", "")
        types = [t] if isinstance(t, str) else (t or [])
        if any(str(x).lower() == "realestatelisting" for x in types):
            return item
    return None


def _redfin_locality_from_url(url: str) -> Dict[str, Optional[str]]:
    """Derive city/state/zip/street from the URL slug, e.g.
    ``/CA/Santa-Rosa/7455-Foothill-Ranch-Rd-95404/home/2277302``."""
    parts = [p for p in urlparse(url).path.split("/") if p]
    out: Dict[str, Optional[str]] = {"city": None, "state": None, "zip": None, "street": None}
    if len(parts) >= 3:
        if len(parts[0]) == 2 and parts[0].isalpha():
            out["state"] = parts[0].upper()
        out["city"] = parts[1].replace("-", " ") or None
        slug = parts[2]
        m = re.search(r"-(\d{5})$", slug)
        if m:
            out["zip"] = m.group(1)
            slug = slug[: m.start()]
        out["street"] = slug.replace("-", " ") or None
    return out


def _redfin_status(listing_ld: Optional[Dict[str, Any]]) -> str:
    """Derive status from the subject listing's offer availability (reliable),
    not page text — the similar-homes sidebar contains "sold" and would
    misclassify an active listing."""
    if isinstance(listing_ld, dict):
        offers = listing_ld.get("offers")
        if isinstance(offers, dict):
            avail = str(offers.get("availability", "")).lower()
            if "soldout" in avail or "discontinued" in avail:
                return "sold"
            if "instock" in avail or "limited" in avail:
                return "for_sale"
    return "for_sale"


def scrape_redfin(url: str) -> NormalizedListing:
    """Direct-fetch a Redfin listing.

    Uses the subject ``RealEstateListing`` JSON-LD block for street / price /
    photos / description, and the URL slug for city / state / zip (those aren't
    in that block). Enriches geo & beds/baths from a nested ``mainEntity`` when
    present. Avoids the generic JSON-LD merge, which would grab a similar-home.
    """
    html = fetch_html(url)
    listing_ld = _find_realestate_listing(html)
    if listing_ld is None:
        raise ScrapeBlocked("no RealEstateListing data found in Redfin page")

    loc = _redfin_locality_from_url(url)
    offers = listing_ld.get("offers") if isinstance(listing_ld.get("offers"), dict) else {}
    price = _to_float(offers.get("price"))
    photos = _collect_image_urls(listing_ld.get("image"))

    # Optional richer fields from a nested residence entity.
    lat = lng = beds = baths = sqft = None
    main = listing_ld.get("mainEntity")
    if isinstance(main, dict):
        geo = main.get("geo")
        if isinstance(geo, dict):
            lat = _to_float(geo.get("latitude"))
            lng = _to_float(geo.get("longitude"))
        beds = _to_float(main.get("numberOfBedrooms"))
        baths = _to_float(main.get("numberOfBathroomsTotal"))
        fs = main.get("floorSize")
        if isinstance(fs, dict):
            sqft = _to_float(fs.get("value"))

    street = listing_ld.get("name") or loc["street"]
    if not (street or price):
        raise ScrapeBlocked("no listing data found in Redfin page")

    return NormalizedListing(
        source_id=_redfin_listing_id(url),
        source_url=listing_ld.get("url") or url,
        address=street,
        city=loc["city"],
        state=loc["state"],
        zip=loc["zip"],
        latitude=lat,
        longitude=lng,
        price=price,
        beds=beds,
        baths=baths,
        sqft=sqft,
        status=_redfin_status(listing_ld),
        description=listing_ld.get("description"),
        photo_urls=photos,
        raw={"_scraped": "jsonld_redfin", "jsonld": listing_ld, "url": url},
    )


# ── Dispatch by hostname ─────────────────────────────────────────────────────
def detect_source(url: str) -> Optional[str]:
    u = url.lower()
    if "zillow.com" in u:
        return "zillow"
    if "redfin.com" in u:
        return "redfin"
    return None
