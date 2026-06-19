"""Geometry helpers for map-drawn region search (see routers/ingest.py).

The listing sources search by area (city/zip), not arbitrary geofences, so we
bridge a drawn shape to searchable areas using the pgeocode US ZIP dataset
(ZIP centroids): find the ZIPs inside the shape, dedupe to unique cities to
search, then filter the returned listings back down to the exact shape with a
point-in-shape test. Pure-python math; the only data dependency is pgeocode
(already required for Zillow-URL reconstruction).
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

EARTH_RADIUS_MI = 3958.7613


@dataclass
class Shape:
    """A drawn region. One of: rectangle (bbox), circle (center+radius), polygon."""

    kind: str  # rectangle | circle | polygon
    # rectangle: (min_lat, min_lng, max_lat, max_lng)
    bbox: Optional[Tuple[float, float, float, float]] = None
    # circle:
    center: Optional[Tuple[float, float]] = None  # (lat, lng)
    radius_mi: Optional[float] = None
    # polygon: [(lat, lng), ...]
    points: List[Tuple[float, float]] = field(default_factory=list)


def haversine_mi(a: Tuple[float, float], b: Tuple[float, float]) -> float:
    lat1, lng1, lat2, lng2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    d = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(
        (lng2 - lng1) / 2
    ) ** 2
    return 2 * EARTH_RADIUS_MI * math.asin(math.sqrt(d))


def _point_in_polygon(lat: float, lng: float, poly: List[Tuple[float, float]]) -> bool:
    """Ray-casting point-in-polygon. poly is [(lat, lng), ...]."""
    inside = False
    n = len(poly)
    j = n - 1
    for i in range(n):
        yi, xi = poly[i]
        yj, xj = poly[j]
        if (xi > lng) != (xj > lng):
            at = (yj - yi) * (lng - xi) / ((xj - xi) or 1e-12) + yi
            if lat < at:
                inside = not inside
        j = i
    return inside


def contains(shape: Shape, lat: float, lng: float) -> bool:
    """Is the (lat, lng) point inside the shape?"""
    if lat is None or lng is None:
        return False
    if shape.kind == "rectangle" and shape.bbox:
        min_lat, min_lng, max_lat, max_lng = shape.bbox
        return min_lat <= lat <= max_lat and min_lng <= lng <= max_lng
    if shape.kind == "circle" and shape.center and shape.radius_mi is not None:
        return haversine_mi(shape.center, (lat, lng)) <= shape.radius_mi
    if shape.kind == "polygon" and len(shape.points) >= 3:
        return _point_in_polygon(lat, lng, shape.points)
    return False


def bounding_box(shape: Shape) -> Tuple[float, float, float, float]:
    """(min_lat, min_lng, max_lat, max_lng) enclosing the shape."""
    if shape.kind == "rectangle" and shape.bbox:
        return shape.bbox
    if shape.kind == "circle" and shape.center and shape.radius_mi is not None:
        lat, lng = shape.center
        dlat = shape.radius_mi / 69.0
        dlng = shape.radius_mi / (69.0 * max(math.cos(math.radians(lat)), 0.01))
        return (lat - dlat, lng - dlng, lat + dlat, lng + dlng)
    if shape.kind == "polygon" and shape.points:
        lats = [p[0] for p in shape.points]
        lngs = [p[1] for p in shape.points]
        return (min(lats), min(lngs), max(lats), max(lngs))
    raise ValueError(f"invalid shape: {shape.kind}")


# ── pgeocode-backed ZIP/city lookup ──────────────────────────────────────────
_nomi = None


def _zip_dataframe():
    global _nomi
    import pgeocode  # lazy: heavy pandas import

    if _nomi is None:
        _nomi = pgeocode.Nominatim("us")
    return _nomi._data


def cities_in_shape(shape: Shape, max_cities: int = 15) -> Tuple[List[str], bool]:
    """Unique "City, ST" search areas whose ZIP centroid lies inside the shape.

    Returns (cities, capped) — ``capped`` is True if more than ``max_cities``
    were found and the list was truncated (so callers can warn the user)."""
    df = _zip_dataframe()
    min_lat, min_lng, max_lat, max_lng = bounding_box(shape)
    box = df[
        df.latitude.between(min_lat, max_lat) & df.longitude.between(min_lng, max_lng)
    ].dropna(subset=["latitude", "longitude", "place_name", "state_code"])

    seen = set()
    cities: List[str] = []
    # Nearest-first for circles so a capped list still covers the center.
    rows = box.itertuples()
    if shape.kind == "circle" and shape.center:
        rows = sorted(
            box.itertuples(),
            key=lambda r: haversine_mi(shape.center, (r.latitude, r.longitude)),
        )
    for r in rows:
        if not contains(shape, r.latitude, r.longitude):
            continue
        key = f"{r.place_name}, {r.state_code}"
        if key not in seen:
            seen.add(key)
            cities.append(key)

    capped = len(cities) > max_cities
    return cities[:max_cities], capped
