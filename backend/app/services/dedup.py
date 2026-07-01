"""Cross-source duplicate detection.

The same physical home appears on multiple sources under different ids, so we
match on the property itself: normalized street address + ZIP first (strong
when present), then coordinate proximity as a fallback. Used by the ingest
upsert to merge a second source onto an existing Property instead of creating a
duplicate row.
"""
from __future__ import annotations

import re
from typing import Optional

from sqlalchemy.orm import Session

from ..models import Property
from .geo import haversine_mi

# Street-suffix normalization so "123 Main Street" == "123 Main St".
_SUFFIX = {
    "street": "st", "avenue": "ave", "av": "ave", "road": "rd", "drive": "dr",
    "lane": "ln", "boulevard": "blvd", "court": "ct", "place": "pl", "circle": "cir",
    "terrace": "ter", "trail": "trl", "parkway": "pkwy", "highway": "hwy",
    "way": "way", "square": "sq", "loop": "loop",
}
_UNIT_WORDS = re.compile(r"\b(apt|apartment|unit|ste|suite|#|spc|space|lot)\b.*$")


def normalize_address(street: Optional[str], zipc: Optional[str]) -> Optional[str]:
    """A comparable key like ``"123 main st|95404"``, or None if unusable."""
    if not street:
        return None
    s = street.lower().strip()
    s = _UNIT_WORDS.sub("", s)                # drop unit/apt tails
    s = re.sub(r"[^a-z0-9 ]", " ", s)         # keep alphanumerics
    tokens = [_SUFFIX.get(t, t) for t in s.split()]
    s = " ".join(tokens).strip()
    if not s:
        return None
    z = (zipc or "").strip()[:5]
    return f"{s}|{z}"


# ~30 m tolerance for the coordinate fallback (condos share a building point,
# so coord matches also require the same bed count).
_COORD_TOL_MI = 30 / 1609.344
_BBOX_DEG = 0.0005  # ~55 m, a cheap pre-filter box


def find_matching_property(db: Session, listing) -> Optional[Property]:
    """Return an existing Property that is the same home as ``listing``, or None.

    ``listing`` is a NormalizedListing (has address/zip/latitude/longitude/beds).
    """
    key = normalize_address(getattr(listing, "address", None), getattr(listing, "zip", None))
    if key:
        zipc = (getattr(listing, "zip", None) or "").strip()[:5]
        candidates = (
            db.query(Property).filter(Property.zip.isnot(None)).all()
            if not zipc
            else db.query(Property).filter(Property.zip == getattr(listing, "zip"))
            .all()
        )
        for p in candidates:
            if normalize_address(p.address, p.zip) == key:
                return p

    lat, lng = getattr(listing, "latitude", None), getattr(listing, "longitude", None)
    if lat is not None and lng is not None:
        near = (
            db.query(Property)
            .filter(
                Property.latitude.between(lat - _BBOX_DEG, lat + _BBOX_DEG),
                Property.longitude.between(lng - _BBOX_DEG, lng + _BBOX_DEG),
            )
            .all()
        )
        lbeds = getattr(listing, "beds", None)
        for p in near:
            if p.latitude is None or p.longitude is None:
                continue
            if haversine_mi((lat, lng), (p.latitude, p.longitude)) <= _COORD_TOL_MI:
                # Require matching beds when both known (guards condo buildings).
                if lbeds is None or p.beds is None or lbeds == p.beds:
                    return p
    return None
