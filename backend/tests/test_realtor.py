"""Realtor.com (HomeHarvest) tests: normalize() field mapping with fake model
objects, plus the /ingest/realtor/search endpoint with realtor.search
monkeypatched (no network, no pandas import)."""
from types import SimpleNamespace

import pytest

from app.services import realtor
from app.services.realtor import RealtorUnavailable, normalize
from app.services.zillow import NormalizedListing


def _fake_prop(**over):
    """A HomeHarvest-shaped Property (attribute access; nested addr/desc)."""
    desc = SimpleNamespace(
        primary_photo="http://img/primary.jpg",
        alt_photos=["http://img/primary.jpg", "http://img/2.jpg"],  # dup primary
        style="SINGLE_FAMILY",
        type="single_family",
        beds=4,
        baths_full=3,
        baths_half=1,
        sqft=2600,
        lot_sqft=8000,
        year_built=2009,
        text="Lovely home near the foothills.",
    )
    addr = SimpleNamespace(
        full_line="123 Maple St",
        street="123 Maple St",
        city="Boulder",
        state="CO",
        zip="80302",
    )
    base = dict(
        property_id=7654321,
        property_url="https://www.realtor.com/realestateandhomes-detail/x_M7654321",
        status="CONTINGENT",
        address=addr,
        description=desc,
        list_price=1450000,
        latitude=40.01,
        longitude=-105.27,
        days_on_mls=12,
        county="Boulder",
    )
    base.update(over)
    return SimpleNamespace(**base)


def test_normalize_maps_fields():
    n = normalize(_fake_prop())
    assert n.source_id == "7654321"
    assert n.source_url.endswith("M7654321")
    assert n.address == "123 Maple St"
    assert n.city == "Boulder" and n.state == "CO" and n.zip == "80302"
    assert n.county == "Boulder"
    assert n.price == 1450000
    assert n.beds == 4
    assert n.baths == 3.5  # 3 full + 1 half
    assert n.sqft == 2600 and n.lot_size == 8000
    assert n.year_built == 2009
    assert n.property_type == "SINGLE_FAMILY"
    assert n.status == "pending"  # CONTINGENT → pending
    assert n.days_on_market == 12
    # primary first, dup removed
    assert n.photo_urls == ["http://img/primary.jpg", "http://img/2.jpg"]


def test_normalize_is_defensive_on_thin_prop():
    n = normalize(SimpleNamespace(property_id=5, property_url=None,
                                  address=None, description=None, status=None))
    assert n.source_id == "5"
    assert n.status == "for_sale"  # default
    assert n.price is None and n.baths is None and n.photo_urls == []


def test_search_raises_when_disabled(monkeypatch):
    monkeypatch.setattr(realtor.settings, "realtor_enabled", False)
    with pytest.raises(RealtorUnavailable):
        realtor.search("Boulder, CO")


def test_search_rejects_bad_listing_type():
    with pytest.raises(RealtorUnavailable):
        realtor.search("Boulder, CO", listing_type="bogus")


def test_realtor_search_ingest_endpoint(client, monkeypatch):
    """End-to-end upsert via a monkeypatched search (no homeharvest call)."""
    listings = [
        NormalizedListing(source_id="111", source_url="http://realtor/111",
                          city="Boulder", price=900000, beds=3, status="for_sale"),
        NormalizedListing(source_id="222", source_url="http://realtor/222",
                          city="Boulder", price=1200000, beds=4, status="pending"),
    ]
    monkeypatch.setattr(realtor, "search", lambda *a, **k: list(listings))

    r = client.post("/ingest/realtor/search", json={"location": "Boulder, CO"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["created"] == 2 and body["updated"] == 0
    pid = body["property_ids"][0]
    detail = client.get(f"/properties/{pid}").json()
    assert detail["source"] == "realtor"

    # Re-running the same search updates rather than duplicating.
    r2 = client.post("/ingest/realtor/search", json={"location": "Boulder, CO"})
    assert r2.json()["updated"] == 2 and r2.json()["created"] == 0


def test_realtor_search_unavailable_returns_503(client, monkeypatch):
    def _boom(*a, **k):
        raise RealtorUnavailable("blocked")
    monkeypatch.setattr(realtor, "search", _boom)
    r = client.post("/ingest/realtor/search", json={"location": "Nowhere"})
    assert r.status_code == 503
