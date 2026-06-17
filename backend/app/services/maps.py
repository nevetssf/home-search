"""Google Maps Platform client — geocode / places-nearby / distance-matrix.

All calls are server-side (key never reaches the browser) and every result is
cached in ``PlaceDistance`` (PLAN.md §6, §7). If no API key is configured the
methods raise ``MapsUnavailable`` so callers can degrade gracefully.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

import httpx

from ..config import settings

GEOCODE_URL = "https://maps.googleapis.com/maps/api/geocode/json"
PLACES_NEARBY_URL = "https://maps.googleapis.com/maps/api/place/nearbysearch/json"
DISTANCE_MATRIX_URL = "https://maps.googleapis.com/maps/api/distancematrix/json"

# Amenity category → Google Places "type" (downtown handled via text/locality).
CATEGORY_PLACE_TYPE = {
    "grocery": "supermarket",
    "cafe": "cafe",
    "restaurant": "restaurant",
}


class MapsUnavailable(RuntimeError):
    """Raised when no Google Maps API key is configured."""


@dataclass
class NearestPlace:
    name: str
    address: Optional[str]
    latitude: float
    longitude: float
    raw: dict


@dataclass
class DistanceResult:
    distance_meters: Optional[float]
    duration_seconds: Optional[float]
    raw: dict


class MapsClient:
    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key if api_key is not None else settings.google_maps_api_key

    def _require_key(self):
        if not self.api_key:
            raise MapsUnavailable("GOOGLE_MAPS_API_KEY is not configured")

    def geocode(self, address: str) -> Optional[tuple[float, float]]:
        self._require_key()
        with httpx.Client(timeout=15) as client:
            r = client.get(
                GEOCODE_URL, params={"address": address, "key": self.api_key}
            )
            r.raise_for_status()
            results = r.json().get("results", [])
        if not results:
            return None
        loc = results[0]["geometry"]["location"]
        return loc["lat"], loc["lng"]

    def nearest(
        self, lat: float, lng: float, category: str, radius_m: int = 8000
    ) -> Optional[NearestPlace]:
        """Closest place of ``category`` to (lat,lng) via Places Nearby."""
        self._require_key()
        place_type = CATEGORY_PLACE_TYPE.get(category)
        params = {
            "location": f"{lat},{lng}",
            "rankby": "distance" if not place_type else "prominence",
            "key": self.api_key,
        }
        if place_type:
            params["type"] = place_type
            params["radius"] = radius_m
        else:
            # downtown / generic — keyword search ranked by distance
            params["keyword"] = category
            params["rankby"] = "distance"
        with httpx.Client(timeout=15) as client:
            r = client.get(PLACES_NEARBY_URL, params=params)
            r.raise_for_status()
            results = r.json().get("results", [])
        if not results:
            return None
        top = results[0]
        loc = top["geometry"]["location"]
        return NearestPlace(
            name=top.get("name", category),
            address=top.get("vicinity"),
            latitude=loc["lat"],
            longitude=loc["lng"],
            raw=top,
        )

    def distance(
        self,
        origin: tuple[float, float],
        dest: tuple[float, float],
        mode: str = "driving",
    ) -> DistanceResult:
        self._require_key()
        params = {
            "origins": f"{origin[0]},{origin[1]}",
            "destinations": f"{dest[0]},{dest[1]}",
            "mode": mode,
            "key": self.api_key,
        }
        with httpx.Client(timeout=15) as client:
            r = client.get(DISTANCE_MATRIX_URL, params=params)
            r.raise_for_status()
            payload = r.json()
        try:
            elem = payload["rows"][0]["elements"][0]
            return DistanceResult(
                distance_meters=elem["distance"]["value"],
                duration_seconds=elem["duration"]["value"],
                raw=elem,
            )
        except (KeyError, IndexError):
            return DistanceResult(None, None, payload)


# Default amenity categories computed on a distance refresh.
DEFAULT_AMENITIES: List[str] = ["grocery", "cafe", "restaurant", "downtown"]
