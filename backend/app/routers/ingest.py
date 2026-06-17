"""Listing ingestion: Zillow URL/area + Redfin CSV (PLAN.md §6).

Strategy: cache every raw response in ``Property.raw_payload``, download promo
photos locally (persist + privacy), upsert by ``(source, source_id)``. Any API
failure degrades to HTTP 503 / partial result so manual entry stays the
graceful fallback.
"""
from datetime import datetime
from typing import Optional

import httpx
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy.orm import Session

from .. import schemas
from ..auth import get_current_user
from ..database import get_db
from ..models import Media, Property, StatusHistory, User
from ..services import redfin_csv
from ..services.storage import get_storage, make_key
from ..services.zillow import (
    NormalizedListing,
    ZillowClient,
    ZillowUnavailable,
    normalize,
)

router = APIRouter(prefix="/ingest", tags=["ingest"])

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


@router.post("/zillow/url", response_model=schemas.IngestResult)
def ingest_zillow_url(
    payload: schemas.ZillowURLIngest,
    download_photos: bool = True,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    client = ZillowClient()
    try:
        raw = client.fetch_by_url(payload.url)
    except ZillowUnavailable as e:
        raise HTTPException(503, str(e))
    listing = normalize(raw)
    if not listing.source_url:
        listing.source_url = payload.url
    prop, created = _upsert(db, "zillow", listing, download_photos)
    db.commit()
    return schemas.IngestResult(
        created=int(created),
        updated=int(not created),
        property_ids=[prop.id],
    )


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
