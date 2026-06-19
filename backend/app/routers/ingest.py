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
from ..models import Media, Property, StatusHistory, User
from ..services import realtor, redfin_csv, scrape
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
    db: Session, source: str, listing: NormalizedListing, download: bool
) -> tuple[Property, bool]:
    """Create or update a property from a normalized listing. Returns (prop, created)."""
    prop: Optional[Property] = None
    if listing.source_id:
        prop = (
            db.query(Property)
            .filter(Property.source == source, Property.source_id == listing.source_id)
            .first()
        )
    created = prop is None
    if created:
        prop = Property(source=source, source_id=listing.source_id)
        db.add(prop)

    for f in _LISTING_FIELDS:
        val = getattr(listing, f, None)
        if val is not None:
            setattr(prop, f, val)
    prop.source_url = listing.source_url or prop.source_url
    prop.raw_payload = listing.raw or prop.raw_payload
    prop.last_synced_at = datetime.utcnow()

    if prop.status != listing.status:
        db.add(
            StatusHistory(
                property_id=prop.id if prop.id else None,
                status=listing.status,
                source=source,
            )
        )
        prop.status = listing.status

    db.flush()  # ensure prop.id for media / history

    if created and download and listing.photo_urls:
        _download_photos(db, prop, listing.photo_urls)

    return prop, created


def _ingest_one(db: Session, source: str, listing: NormalizedListing, download: bool):
    prop, created = _upsert(db, source, listing, download)
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
    return _ingest_one(db, source, listing, download_photos)


@router.post("/zillow/url", response_model=schemas.IngestResult)
def ingest_zillow_url(
    payload: schemas.ZillowURLIngest,
    download_photos: bool = True,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    source, listing = _resolve_zillow_listing(payload.url)
    listing.source_url = listing.source_url or payload.url
    return _ingest_one(db, source, listing, download_photos)


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
    return _ingest_one(db, "redfin", listing, download_photos)


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
            prop, created = _upsert(db, "zillow", normalize(raw), download_photos)
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
            prop, created = _upsert(db, "realtor", listing, download_photos)
            out.property_ids.append(prop.id)
            if created:
                out.created += 1
            else:
                out.updated += 1
        except Exception as e:  # one bad row shouldn't sink the batch
            out.errors.append(str(e)[:200])
    db.commit()
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
            prop, created = _upsert(db, "redfin", listing, download=False)
            out.property_ids.append(prop.id)
            if created:
                out.created += 1
            else:
                out.updated += 1
        except Exception as e:
            out.errors.append(str(e)[:200])
    db.commit()
    return out
