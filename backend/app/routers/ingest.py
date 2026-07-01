"""Listing ingestion: Zillow URL/area + Redfin CSV (PLAN.md §6).

Strategy: cache every raw response in ``Property.raw_payload``, download promo
photos locally (persist + privacy), upsert by ``(source, source_id)``. Any API
failure degrades to HTTP 503 / partial result so manual entry stays the
graceful fallback.
"""
import re
from datetime import datetime
from typing import Optional

import httpx
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy.orm import Session

from .. import schemas
from ..auth import get_current_user
from ..config import settings
from ..database import get_db
from ..models import Media, Property, PropertySource, StatusHistory, User
from ..services import dedup, geo, realtor, redfin_csv, scrape
from ..services.realtor import RealtorUnavailable
from ..services.scrape import ScrapeBlocked
from ..services.storage import get_storage, make_key
from ..services.zillow import (
    NormalizedListing,
    ZillowClient,
    ZillowUnavailable,
    normalize,
)

router = APIRouter(prefix="/ingest", tags=["ingest"])


def _house_number(s: Optional[str]) -> Optional[str]:
    m = re.match(r"\s*(\d+)", s or "")
    return m.group(1) if m else None


def _zillow_realtor_match(parsed: dict) -> Optional[NormalizedListing]:
    """Look the parsed Zillow address up on Realtor.com and return the listing
    ONLY if zip + house number match — Realtor's geocoder otherwise returns a
    silently-wrong nearby home (see the Redfin similar-homes bug)."""
    if not (settings.realtor_enabled and parsed.get("street") and parsed.get("zip")):
        return None
    query = ", ".join(
        p for p in (
            parsed["street"],
            parsed.get("city"),
            f"{parsed.get('state') or ''} {parsed['zip']}".strip(),
        ) if p
    )
    try:
        candidates = realtor.search(location=query, radius=0, limit=8)
    except RealtorUnavailable:
        return None
    want = _house_number(parsed["street"])
    for c in candidates:
        if want and c.zip == parsed["zip"] and _house_number(c.address) == want:
            return c
    return None


def _resolve_zillow_listing(url: str) -> tuple[str, NormalizedListing]:
    """Resolve a Zillow URL to (source, listing) with a graceful fallback chain
    (PLAN.md §6). Zillow bot-walls direct fetches, so: direct scrape → RapidAPI
    (if a key is set) → reconstruct from the URL slug, enriched from Realtor.com
    when zip+house number match, else an accurate address-only stub. Never a
    dead end, never silently-wrong data."""
    # 1. Direct scrape (usually CAPTCHA-blocked, but free when it works).
    try:
        return "zillow", scrape.scrape_zillow(url)
    except ScrapeBlocked:
        pass
    # 2. RapidAPI wrapper, if configured (reliable full data).
    client = ZillowClient()
    if client.api_key:
        try:
            listing = normalize(client.fetch_by_url(url))
            listing.source_url = listing.source_url or url
            return "zillow", listing
        except ZillowUnavailable:
            pass
    # 3. No key / blocked: rebuild from the URL slug (+ pgeocode city/coords).
    parsed = scrape.parse_zillow_url(url)
    if not parsed:
        raise HTTPException(
            502,
            "Zillow blocked the fetch and the URL couldn't be parsed; set "
            "RAPIDAPI_KEY, or add the property manually.",
        )
    match = _zillow_realtor_match(parsed)
    if match:
        match.source_url = url  # keep the Zillow link the user pasted
        return "realtor", match
    stub = NormalizedListing(
        source_id=parsed["zpid"],
        source_url=url,
        address=parsed["street"],
        city=parsed["city"],
        state=parsed["state"],
        zip=parsed["zip"],
        latitude=parsed["lat"],
        longitude=parsed["lng"],
        raw={"_scraped": "zillow_url_slug", **parsed},
    )
    return "zillow", stub

_LISTING_FIELDS = (
    "address city state zip county latitude longitude price beds baths sqft "
    "lot_size year_built property_type days_on_market description"
).split()


def _download_photos(db: Session, prop: Property, urls: list[str], limit: int = 40):
    """Download promo photos locally so they persist and aren't hotlinked."""
    storage = get_storage()
    with httpx.Client(timeout=30, follow_redirects=True) as client:
        for i, url in enumerate(urls[:limit]):
            try:
                r = client.get(url)
                r.raise_for_status()
            except Exception:
                continue
            key = make_key(prop.id, url.split("?")[0])
            storage.save(key, r.content, content_type=r.headers.get("content-type"))
            db.add(
                Media(
                    property_id=prop.id,
                    kind="photo",
                    origin="promo",
                    storage_key=key,
                    content_type=r.headers.get("content-type"),
                    sort_order=i,
                )
            )


def _upsert(
    db: Session,
    source: str,
    listing: NormalizedListing,
    download: bool,
    origin: Optional[str] = None,
) -> tuple[Property, bool]:
    """Create or update a property from a normalized listing. Returns (prop, created).

    ``origin`` records how the property first entered the app; set only on
    creation so a later refresh never rewrites the original provenance.

    Resolution order: (1) same source+id → update that source link's property;
    (2) cross-source duplicate (dedup by address/coords) → attach a new source
    link to the existing property; (3) otherwise create a new property. The
    Property's own source_*/raw fields mirror the primary (first) source."""
    now = datetime.utcnow()

    link: Optional[PropertySource] = None
    if listing.source_id:
        link = (
            db.query(PropertySource)
            .filter(PropertySource.source == source, PropertySource.source_id == listing.source_id)
            .first()
        )

    if link:
        prop = link.property
        created = False
    else:
        prop = dedup.find_matching_property(db, listing)
        created = prop is None
        if created:
            prop = Property(
                source=source, source_id=listing.source_id,
                origin=origin, source_url=listing.source_url,
            )
            db.add(prop)
            db.flush()  # assign prop.id for the FK below
        link = PropertySource(
            property_id=prop.id, source=source, source_id=listing.source_id,
            source_url=listing.source_url, origin=origin, raw_payload=listing.raw,
            last_synced_at=now,
        )
        db.add(link)

    # Refresh this source link.
    link.source_url = listing.source_url or link.source_url
    link.raw_payload = listing.raw or link.raw_payload
    link.last_synced_at = now

    # Canonical property facts — latest sync wins.
    for f in _LISTING_FIELDS:
        val = getattr(listing, f, None)
        if val is not None:
            setattr(prop, f, val)
    prop.last_synced_at = now
    prop.source_url = prop.source_url or listing.source_url
    prop.raw_payload = prop.raw_payload or listing.raw

    # Status history (append-only on change; always record the initial status).
    if created:
        prop.status = listing.status
        db.add(StatusHistory(property_id=prop.id, status=listing.status, source=source))
    elif prop.status != listing.status:
        db.add(StatusHistory(property_id=prop.id, status=listing.status, source=source))
        prop.status = listing.status

    db.flush()

    if created and download and listing.photo_urls:
        _download_photos(db, prop, listing.photo_urls)

    return prop, created


def _ingest_one(
    db: Session, source: str, listing: NormalizedListing, download: bool, origin: str
):
    prop, created = _upsert(db, source, listing, download, origin=origin)
    db.commit()
    return schemas.IngestResult(
        created=int(created), updated=int(not created), property_ids=[prop.id]
    )


@router.post("/url", response_model=schemas.IngestResult)
def ingest_url(
    payload: schemas.ZillowURLIngest,
    download_photos: bool = True,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    """Unified entry: detect Zillow vs Redfin from the URL and ingest. Scrapes
    the page directly (no API key required); Zillow falls back to RapidAPI if a
    key is configured, and to manual entry if everything fails."""
    detected = scrape.detect_source(payload.url)
    if detected == "zillow":
        source, listing = _resolve_zillow_listing(payload.url)
    elif detected == "redfin":
        source = "redfin"
        try:
            listing = scrape.scrape_redfin(payload.url)
        except ScrapeBlocked as e:
            raise HTTPException(502, f"Could not scrape Redfin ({e}); add manually.")
    else:
        raise HTTPException(400, "URL must be a zillow.com or redfin.com listing")
    listing.source_url = listing.source_url or payload.url
    return _ingest_one(db, source, listing, download_photos, origin="url")


@router.post("/zillow/url", response_model=schemas.IngestResult)
def ingest_zillow_url(
    payload: schemas.ZillowURLIngest,
    download_photos: bool = True,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    source, listing = _resolve_zillow_listing(payload.url)
    listing.source_url = listing.source_url or payload.url
    return _ingest_one(db, source, listing, download_photos, origin="url")


@router.post("/redfin/url", response_model=schemas.IngestResult)
def ingest_redfin_url(
    payload: schemas.ZillowURLIngest,
    download_photos: bool = True,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    try:
        listing = scrape.scrape_redfin(payload.url)
    except ScrapeBlocked as e:
        raise HTTPException(502, f"Could not scrape Redfin ({e}); add manually.")
    listing.source_url = listing.source_url or payload.url
    return _ingest_one(db, "redfin", listing, download_photos, origin="url")


@router.post("/zillow/search", response_model=schemas.IngestResult)
def ingest_zillow_search(
    payload: schemas.ZillowSearchIngest,
    download_photos: bool = False,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    client = ZillowClient()
    filters = {k: v for k, v in payload.model_dump().items() if v is not None}
    # Map our names to the wrapper's expected query params.
    params = {
        "location": filters.get("location"),
        "status_type": filters.get("status_type", "ForSale"),
    }
    for src, dst in (
        ("min_price", "minPrice"),
        ("max_price", "maxPrice"),
        ("beds_min", "bedsMin"),
        ("home_type", "home_type"),
    ):
        if filters.get(src) is not None:
            params[dst] = filters[src]

    try:
        results = client.search(**params)
    except ZillowUnavailable as e:
        raise HTTPException(503, str(e))

    out = schemas.IngestResult()
    for raw in results:
        try:
            prop, created = _upsert(db, "zillow", normalize(raw), download_photos, origin="zillow_search")
            out.property_ids.append(prop.id)
            if created:
                out.created += 1
            else:
                out.updated += 1
        except Exception as e:  # one bad row shouldn't sink the batch
            out.errors.append(str(e)[:200])
    db.commit()
    return out


@router.post("/realtor/search", response_model=schemas.IngestResult)
def ingest_realtor_search(
    payload: schemas.RealtorSearchIngest,
    download_photos: bool = False,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    """Area/criteria search on Realtor.com (via HomeHarvest, no API key). Upserts
    each result by ``(source='realtor', source_id)`` — the same house from
    Zillow stays a separate row (cross-source dedup is future work)."""
    try:
        listings = realtor.search(
            payload.location,
            listing_type=payload.listing_type,
            radius=payload.radius,
            beds_min=payload.beds_min,
            baths_min=payload.baths_min,
            price_min=payload.price_min,
            price_max=payload.price_max,
            sqft_min=payload.sqft_min,
            sqft_max=payload.sqft_max,
            past_days=payload.past_days,
        )
    except RealtorUnavailable as e:
        raise HTTPException(503, str(e))

    out = schemas.IngestResult()
    for listing in listings:
        try:
            prop, created = _upsert(db, "realtor", listing, download_photos, origin="realtor_search")
            out.property_ids.append(prop.id)
            if created:
                out.created += 1
            else:
                out.updated += 1
        except Exception as e:  # one bad row shouldn't sink the batch
            out.errors.append(str(e)[:200])
    db.commit()
    return out


def _to_shape(s: schemas.RegionShape) -> geo.Shape:
    """Validate a drawn region payload into a geo.Shape."""
    if s.kind == "rectangle":
        if not s.bbox or len(s.bbox) != 4:
            raise HTTPException(400, "rectangle needs bbox=[min_lat,min_lng,max_lat,max_lng]")
        return geo.Shape(kind="rectangle", bbox=tuple(s.bbox))
    if s.kind == "circle":
        if not s.center or len(s.center) != 2 or s.radius_mi is None:
            raise HTTPException(400, "circle needs center=[lat,lng] and radius_mi")
        return geo.Shape(kind="circle", center=tuple(s.center), radius_mi=s.radius_mi)
    if s.kind == "polygon":
        if not s.points or len(s.points) < 3:
            raise HTTPException(400, "polygon needs >=3 points=[[lat,lng],...]")
        return geo.Shape(kind="polygon", points=[tuple(p) for p in s.points])
    raise HTTPException(400, f"unknown shape kind: {s.kind}")


def _enabled_sources(requested: list[str]) -> list[str]:
    """Sources to query = requested ∩ available (or all available if none given).
    Realtor is available when enabled; Zillow only when a RapidAPI key is set."""
    available = []
    if settings.realtor_enabled:
        available.append("realtor")
    if settings.rapidapi_key:
        available.append("zillow")
    return [s for s in requested if s in available] if requested else available


_ZILLOW_STATUS = {"for_sale": "ForSale", "pending": "ForSale", "sold": "RecentlySold"}


def _search_city(source: str, city: str, crit, listing_type: str) -> list[NormalizedListing]:
    """Query one source for a city with the shared criteria → normalized listings."""
    if source == "realtor":
        return realtor.search(
            city, listing_type=listing_type,
            beds_min=crit.beds_min, baths_min=crit.baths_min,
            price_min=crit.price_min, price_max=crit.price_max,
            sqft_min=crit.sqft_min, sqft_max=crit.sqft_max,
        )
    if source == "zillow":
        client = ZillowClient()
        params: dict = {"location": city, "status_type": _ZILLOW_STATUS.get(listing_type, "ForSale")}
        if crit.price_min:
            params["minPrice"] = crit.price_min
        if crit.price_max:
            params["maxPrice"] = crit.price_max
        if crit.beds_min:
            params["bedsMin"] = crit.beds_min
        if crit.home_type:
            params["home_type"] = crit.home_type
        return [normalize(r) for r in client.search(**params)]
    return []


def _find_existing(db: Session, source: str, listing: NormalizedListing) -> Optional[Property]:
    """The existing property for this listing (same-source link or cross-source dup)."""
    if listing.source_id:
        link = (
            db.query(PropertySource)
            .filter(PropertySource.source == source, PropertySource.source_id == listing.source_id)
            .first()
        )
        if link:
            return link.property
    return dedup.find_matching_property(db, listing)


@router.post("/region", response_model=schemas.IngestResult)
def ingest_region(
    payload: schemas.RegionSearchIngest,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    """Search the listing source within map-drawn region(s) (PLAN.md §6, extended).

    Bridges the drawn shape to area searches: ZIP centroids inside the shape →
    unique cities (capped) → Realtor.com search each → filter the results to the
    points actually inside the shape → upsert. Keyless (Realtor/HomeHarvest)."""
    if not payload.shapes:
        raise HTTPException(400, "draw at least one region")
    sources = _enabled_sources(payload.sources)
    if not sources:
        raise HTTPException(503, "No search sources available (enable Realtor or set RAPIDAPI_KEY).")

    shapes = [_to_shape(s) for s in payload.shapes]

    # Collect the unique cities to search across all shapes (bounded).
    cities: list[str] = []
    seen_cities: set[str] = set()
    capped = False
    for shp in shapes:
        cs, cap = geo.cities_in_shape(shp, max_cities=payload.max_cities)
        capped = capped or cap
        for c in cs:
            if c not in seen_cities:
                seen_cities.add(c)
                cities.append(c)
    cities = cities[: payload.max_cities]

    out = schemas.IngestResult()
    if not cities:
        out.errors.append("No US ZIP centroids fall inside the region(s) drawn.")
        return out

    # Query every enabled source per city; dedupe within-source by id/address.
    # (Cross-source duplicates are merged onto one property at upsert time.)
    found: dict = {}
    for source in sources:
        for city in cities:
            try:
                for listing in _search_city(source, city, payload, payload.listing_type):
                    key = f"{source}:{listing.source_id or listing.address}|{listing.zip}"
                    found.setdefault(key, (source, listing))
            except (RealtorUnavailable, ZillowUnavailable) as e:
                out.errors.append(f"{source}/{city}: {str(e)[:100]}")
            except Exception as e:  # one bad city shouldn't sink the batch
                out.errors.append(f"{source}/{city}: {str(e)[:100]}")

    # Keep only listings whose coordinates fall inside one of the drawn shapes.
    for source, listing in found.values():
        if listing.latitude is None or listing.longitude is None:
            out.skipped += 1
            continue
        if not any(geo.contains(s, listing.latitude, listing.longitude) for s in shapes):
            out.skipped += 1
            continue
        try:
            # Savepoint per listing: a bad row rolls back just itself and leaves
            # the session usable, instead of poisoning the whole batch.
            with db.begin_nested():
                prop, created = _upsert(db, source, listing, download=False, origin="region_search")
            out.property_ids.append(prop.id)
            out.created += int(created)
            out.updated += int(not created)
        except Exception as e:
            out.errors.append(str(e)[:120])
    db.commit()

    if capped:
        out.errors.append(
            f"Region covers more than {payload.max_cities} areas; searched the "
            "closest/first ones. Draw smaller regions for full coverage."
        )
    return out


@router.post("/refresh", response_model=schemas.IngestResult)
def ingest_refresh(
    payload: schemas.RefreshIngest,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    """The "Update" button: find newly-listed properties within the search
    region(s) and refresh the status/details of existing properties (keyless,
    via Realtor.com).

    One city-search pass covers both: cities inside the search regions (to find
    new for-sale listings) plus the cities of existing properties (to detect
    for_sale → pending/sold transitions). Existing properties are matched by
    source_id and updated in place; new listings are only created when they fall
    inside a search region, so the DB isn't flooded with a whole city."""
    sources = _enabled_sources(payload.sources)
    if not sources:
        raise HTTPException(503, "No search sources available (enable Realtor or set RAPIDAPI_KEY).")

    region_shapes = [_to_shape(s) for s in payload.search_regions]

    existing = db.query(Property).filter(Property.archived.is_(False)).all()

    # Cities: inside the search regions (new) + those of existing props (status
    # refresh), deduped and capped.
    cities: list[str] = []
    seen: set[str] = set()
    capped = False
    for shp in region_shapes:
        cs, cap = geo.cities_in_shape(shp, max_cities=payload.max_cities)
        capped = capped or cap
        for c in cs:
            if c not in seen:
                seen.add(c)
                cities.append(c)
    if payload.refresh_existing:
        for p in existing:
            if p.city and p.state:
                c = f"{p.city}, {p.state}"
                if c not in seen:
                    seen.add(c)
                    cities.append(c)
    if len(cities) > payload.max_cities:
        capped = True
        cities = cities[: payload.max_cities]

    out = schemas.IngestResult()
    # Search these statuses so for_sale → pending/sold transitions are visible.
    statuses = (
        ["for_sale", "pending", "sold"] if payload.refresh_existing
        else [payload.listing_type]
    )
    processed: set[str] = set()

    for source in sources:
        for city in cities:
            for lt in statuses:
                try:
                    listings = _search_city(source, city, payload, lt)
                except (RealtorUnavailable, ZillowUnavailable) as e:
                    out.errors.append(f"{source}/{city}/{lt}: {str(e)[:80]}")
                    continue
                except Exception as e:
                    out.errors.append(f"{source}/{city}/{lt}: {str(e)[:80]}")
                    continue
                for listing in listings:
                    pkey = f"{source}:{listing.source_id or listing.address}"
                    if pkey in processed:
                        continue
                    match = _find_existing(db, source, listing)
                    in_region = (
                        bool(region_shapes)
                        and listing.latitude is not None
                        and any(geo.contains(s, listing.latitude, listing.longitude) for s in region_shapes)
                    )
                    # Refresh existing anywhere; create new only inside a region.
                    if not match and not (in_region and lt == "for_sale"):
                        continue
                    processed.add(pkey)
                    prev_status = match.status if match else None
                    try:
                        with db.begin_nested():
                            prop, created = _upsert(
                                db, source, listing, download=False, origin="region_search"
                            )
                    except Exception as e:
                        out.errors.append(str(e)[:100])
                        continue
                    if created:
                        out.created += 1
                        out.property_ids.append(prop.id)
                    else:
                        out.updated += 1
                        if prev_status is not None and prop.status != prev_status:
                            out.status_changed += 1
    db.commit()

    if capped:
        out.errors.append(
            f"Searched up to {payload.max_cities} areas; some regions/cities may "
            "be uncovered. Narrow the search regions for full coverage."
        )
    return out


@router.post("/redfin/csv", response_model=schemas.IngestResult)
def ingest_redfin_csv(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    rows = redfin_csv.parse_csv(file.file.read())
    out = schemas.IngestResult(raw_available=True)
    for row in rows:
        listing = NormalizedListing(
            source_id=row.source_id,
            source_url=row.source_url,
            **{f: getattr(row, f, None) for f in _LISTING_FIELDS},
            raw=row.raw,
        )
        try:
            prop, created = _upsert(db, "redfin", listing, download=False, origin="redfin_csv")
            out.property_ids.append(prop.id)
            if created:
                out.created += 1
            else:
                out.updated += 1
        except Exception as e:
            out.errors.append(str(e)[:200])
    db.commit()
    return out
