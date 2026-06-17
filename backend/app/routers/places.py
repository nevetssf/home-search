"""Points of interest and cached amenity distances (PLAN.md §7).

Distances are computed on demand (or when an address changes) and cached in
``PlaceDistance``; the refresh endpoint degrades gracefully to HTTP 503 if no
Google Maps key is configured rather than failing hard.
"""
from datetime import datetime
from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import schemas
from ..auth import get_current_user
from ..database import get_db
from ..models import PlaceDistance, PointOfInterest, Property, User
from ..services.maps import DEFAULT_AMENITIES, MapsClient, MapsUnavailable

router = APIRouter(tags=["places"])


# ── Points of interest ───────────────────────────────────────────────────────
@router.get("/pois", response_model=List[schemas.POIOut])
def list_pois(
    db: Session = Depends(get_db), current: User = Depends(get_current_user)
):
    return db.query(PointOfInterest).filter(
        PointOfInterest.user_id == current.id
    ).all()


@router.post("/pois", response_model=schemas.POIOut, status_code=201)
def create_poi(
    payload: schemas.POICreate,
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
):
    poi = PointOfInterest(user_id=current.id, **payload.model_dump())
    db.add(poi)
    db.commit()
    db.refresh(poi)
    return poi


@router.delete("/pois/{poi_id}", status_code=204)
def delete_poi(
    poi_id: int,
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
):
    poi = db.get(PointOfInterest, poi_id)
    if not poi or poi.user_id != current.id:
        raise HTTPException(404, "POI not found")
    db.delete(poi)
    db.commit()


# ── Distances ────────────────────────────────────────────────────────────────
@router.get(
    "/properties/{property_id}/distances",
    response_model=List[schemas.PlaceDistanceOut],
)
def get_distances(
    property_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    return (
        db.query(PlaceDistance)
        .filter(PlaceDistance.property_id == property_id)
        .order_by(PlaceDistance.category)
        .all()
    )


@router.post(
    "/properties/{property_id}/distances/refresh",
    response_model=List[schemas.PlaceDistanceOut],
)
def refresh_distances(
    property_id: int,
    mode: str = "driving",
    db: Session = Depends(get_db),
    current: User = Depends(get_current_user),
):
    prop = db.get(Property, property_id)
    if not prop:
        raise HTTPException(404, "Property not found")
    if prop.latitude is None or prop.longitude is None:
        raise HTTPException(400, "Property has no coordinates to compute from")

    client = MapsClient()
    origin = (prop.latitude, prop.longitude)

    # Clear prior cache for this property so the refresh is authoritative.
    db.query(PlaceDistance).filter(
        PlaceDistance.property_id == property_id
    ).delete()

    results: List[PlaceDistance] = []
    try:
        # Standard amenities: find nearest, then measure travel time.
        for category in DEFAULT_AMENITIES:
            place = client.nearest(origin[0], origin[1], category)
            if not place:
                continue
            d = client.distance(origin, (place.latitude, place.longitude), mode)
            results.append(
                PlaceDistance(
                    property_id=property_id,
                    category=category,
                    place_name=place.name,
                    place_address=place.address,
                    distance_meters=d.distance_meters,
                    duration_seconds=d.duration_seconds,
                    mode=mode,
                    raw=d.raw,
                )
            )
        # User points of interest: direct distance to each.
        for poi in db.query(PointOfInterest).filter(
            PointOfInterest.user_id == current.id
        ):
            d = client.distance(origin, (poi.latitude, poi.longitude), mode)
            results.append(
                PlaceDistance(
                    property_id=property_id,
                    category=f"poi:{poi.id}",
                    place_name=poi.name,
                    distance_meters=d.distance_meters,
                    duration_seconds=d.duration_seconds,
                    mode=mode,
                    raw=d.raw,
                )
            )
    except MapsUnavailable as e:
        db.rollback()
        raise HTTPException(503, str(e))

    db.add_all(results)
    db.commit()
    for r in results:
        db.refresh(r)
    return results
