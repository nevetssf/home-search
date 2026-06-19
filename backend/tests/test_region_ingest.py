"""POST /ingest/region — shape → cities → Realtor search → filter → upsert.

geo.cities_in_shape (pgeocode) and realtor.search (network) are monkeypatched
so the test is hermetic and exercises the endpoint's filter/upsert logic.
"""
from app.services import geo
from app.services.zillow import NormalizedListing


def _listing(sid, lat, lng, city="Santa Rosa", price=900000):
    return NormalizedListing(
        source_id=sid, source_url=f"https://realtor.com/{sid}",
        address=f"{sid} Main St", city=city, state="CA", zip="95404",
        latitude=lat, longitude=lng, price=price,
    )


def test_region_search_filters_to_shape(client, monkeypatch):
    from app.routers import ingest as ing
    from app.services import realtor as realtor_mod

    # A 15-mile circle around Santa Rosa.
    circle = {"kind": "circle", "center": [38.44, -122.71], "radius_mi": 15}

    monkeypatch.setattr(geo, "cities_in_shape", lambda shape, max_cities=15: (["Santa Rosa, CA"], False))

    inside = _listing("R1", 38.45, -122.70)     # inside the circle
    outside = _listing("R2", 40.00, -120.00)    # far outside
    no_coords = _listing("R3", None, None)      # unmappable
    monkeypatch.setattr(realtor_mod, "search", lambda *a, **k: [inside, outside, no_coords])

    r = client.post("/ingest/region", json={"shapes": [circle]})
    assert r.status_code == 200, r.text
    res = r.json()
    assert res["created"] == 1                  # only the inside listing
    assert res["skipped"] == 2                  # outside + no-coords filtered out

    pid = res["property_ids"][0]
    detail = client.get(f"/properties/{pid}").json()
    assert detail["source"] == "realtor"
    assert detail["address"] == "R1 Main St"


def test_region_dedupes_cities_and_listings(client, monkeypatch):
    from app.services import realtor as realtor_mod

    rect = {"kind": "rectangle", "bbox": [38.0, -123.0, 39.0, -122.0]}
    monkeypatch.setattr(
        geo, "cities_in_shape",
        lambda shape, max_cities=15: (["Santa Rosa, CA", "Sebastopol, CA"], False),
    )
    # Both city searches return the same listing — must upsert once.
    dup = _listing("DUP", 38.4, -122.7)
    calls = {"n": 0}
    def fake_search(*a, **k):
        calls["n"] += 1
        return [dup]
    monkeypatch.setattr(realtor_mod, "search", fake_search)

    r = client.post("/ingest/region", json={"shapes": [rect]})
    assert r.status_code == 200, r.text
    assert calls["n"] == 2            # searched both cities
    assert r.json()["created"] == 1  # deduped to one property


def test_region_no_cities_returns_empty_result(client, monkeypatch):
    monkeypatch.setattr(geo, "cities_in_shape", lambda shape, max_cities=15: ([], False))
    r = client.post(
        "/ingest/region",
        json={"shapes": [{"kind": "circle", "center": [0, 0], "radius_mi": 1}]},
    )
    assert r.status_code == 200
    assert r.json()["created"] == 0
    assert any("No US ZIP" in e for e in r.json()["errors"])


def test_region_invalid_shape_rejected(client):
    r = client.post("/ingest/region", json={"shapes": [{"kind": "circle"}]})
    assert r.status_code == 400


def test_region_capped_reports_warning(client, monkeypatch):
    from app.services import realtor as realtor_mod
    monkeypatch.setattr(geo, "cities_in_shape", lambda shape, max_cities=15: (["A, CA"], True))
    monkeypatch.setattr(realtor_mod, "search", lambda *a, **k: [])
    r = client.post(
        "/ingest/region",
        json={"shapes": [{"kind": "rectangle", "bbox": [30, -125, 45, -110]}]},
    )
    assert r.status_code == 200
    assert any("smaller regions" in e for e in r.json()["errors"])
