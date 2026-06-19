"""Geometry helpers for map-drawn region search (pure math, no network)."""
from app.services import geo


def test_point_in_rectangle():
    s = geo.Shape(kind="rectangle", bbox=(38.0, -123.0, 38.5, -122.5))
    assert geo.contains(s, 38.2, -122.8)
    assert not geo.contains(s, 39.0, -122.8)   # north of box
    assert not geo.contains(s, 38.2, -121.0)   # east of box


def test_point_in_circle():
    # 10-mile circle around Santa Rosa.
    s = geo.Shape(kind="circle", center=(38.44, -122.71), radius_mi=10)
    assert geo.contains(s, 38.44, -122.71)             # center
    assert geo.contains(s, 38.50, -122.75)             # ~5 mi away
    assert not geo.contains(s, 38.90, -122.71)         # ~32 mi north


def test_point_in_polygon():
    # Triangle.
    s = geo.Shape(kind="polygon", points=[(38.0, -123.0), (38.0, -122.0), (38.6, -122.5)])
    assert geo.contains(s, 38.1, -122.5)   # inside
    assert not geo.contains(s, 38.5, -123.0)  # outside (left of triangle)


def test_haversine_known_distance():
    # SF ~ Santa Rosa is ~50 miles; allow slack.
    d = geo.haversine_mi((37.7749, -122.4194), (38.4405, -122.7144))
    assert 40 < d < 60


def test_bounding_box_circle_encloses():
    s = geo.Shape(kind="circle", center=(38.44, -122.71), radius_mi=10)
    min_lat, min_lng, max_lat, max_lng = geo.bounding_box(s)
    assert min_lat < 38.44 < max_lat and min_lng < -122.71 < max_lng
    # A point on the circle edge (~10 mi north) is within the bbox.
    assert min_lat <= 38.44 + 10 / 69.0 <= max_lat
