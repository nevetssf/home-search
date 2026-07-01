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
    assert detail["origin"] == "region_search"


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


def test_refresh_updates_status_and_finds_new(client, db_session, monkeypatch):
    """/ingest/refresh: refresh an existing property's status (for_sale→pending)
    and add a new for-sale listing found inside a search region."""
    from app.models import Property
    from app.services import realtor as realtor_mod

    # An existing tracked property, currently for_sale.
    db_session.add(Property(
        source="realtor", source_id="R1", origin="region_search", status="for_sale",
        city="Santa Rosa", state="CA", latitude=38.45, longitude=-122.70, price=900000,
    ))
    db_session.commit()

    monkeypatch.setattr(geo, "cities_in_shape", lambda shape, max_cities=20: (["Santa Rosa, CA"], False))

    def fake_search(city, listing_type="for_sale", **k):
        if listing_type == "pending":   # R1 has gone pending
            l = _listing("R1", 38.45, -122.70, price=910000)
            l.status = "pending"
            return [l]
        if listing_type == "for_sale":  # a brand-new listing in the region
            return [_listing("R2", 38.46, -122.71, price=800000)]
        return []
    monkeypatch.setattr(realtor_mod, "search", fake_search)

    circle = {"kind": "circle", "center": [38.44, -122.71], "radius_mi": 10}
    r = client.post("/ingest/refresh", json={"search_regions": [circle], "refresh_existing": True})
    assert r.status_code == 200, r.text
    res = r.json()
    assert res["status_changed"] == 1   # R1 for_sale → pending
    assert res["created"] == 1          # R2 newly found in region

    r1 = db_session.query(Property).filter_by(source_id="R1").first()
    assert r1.status == "pending"
    assert r1.origin == "region_search"  # provenance unchanged by refresh


def test_refresh_stream_emits_progress(client, db_session, monkeypatch):
    """/ingest/refresh/stream yields NDJSON start → city → done events."""
    import json
    from app.models import Property
    from app.services import realtor as realtor_mod

    db_session.add(Property(
        source="realtor", source_id="R1", status="for_sale",
        city="Santa Rosa", state="CA", latitude=38.45, longitude=-122.70,
    ))
    db_session.commit()
    monkeypatch.setattr(geo, "cities_in_shape", lambda shape, max_cities=20: (["Santa Rosa, CA"], False))
    monkeypatch.setattr(realtor_mod, "search", lambda *a, **k: [])

    r = client.post(
        "/ingest/refresh/stream",
        json={"search_regions": [{"kind": "circle", "center": [38.44, -122.71], "radius_mi": 10}]},
    )
    assert r.status_code == 200
    events = [json.loads(l) for l in r.text.strip().split("\n") if l.strip()]
    kinds = [e["event"] for e in events]
    assert kinds[0] == "start"
    assert "city" in kinds
    assert kinds[-1] == "done"
    city_evt = next(e for e in events if e["event"] == "city")
    assert city_evt["index"] == 1 and city_evt["total"] >= 1


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
