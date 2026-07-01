"""Cross-source dedup: address normalization + merge-on-upsert behavior."""
from app.routers.ingest import _upsert
from app.services import dedup
from app.services.zillow import NormalizedListing


def _nl(**kw):
    base = dict(
        source_id=None, source_url=None, address=None, zip=None,
        latitude=None, longitude=None, beds=None, price=None, status="for_sale",
    )
    base.update(kw)
    return NormalizedListing(**base)


def test_normalize_address():
    assert dedup.normalize_address("123 Main Street", "95404") == "123 main st|95404"
    assert dedup.normalize_address("123 Main St Apt 4", "95404-1234") == "123 main st|95404"
    assert dedup.normalize_address("742 Evergreen Terrace", "97403") == "742 evergreen ter|97403"
    assert dedup.normalize_address(None, "95404") is None


def test_cross_source_merges_same_home(db_session):
    """Same house from Realtor then Zillow → one property, two source links."""
    r = _nl(source_id="R1", source_url="http://realtor/R1", address="123 Main St",
            zip="95404", latitude=38.4, longitude=-122.7, beds=3, price=900000)
    p1, c1 = _upsert(db_session, "realtor", r, download=False, origin="region_search")

    z = _nl(source_id="Z1", source_url="http://zillow/Z1", address="123 Main Street",
            zip="95404", latitude=38.4, longitude=-122.7, beds=3, price=910000, status="pending")
    p2, c2 = _upsert(db_session, "zillow", z, download=False, origin="zillow_search")
    db_session.commit()

    assert c1 is True and c2 is False          # second is a dedup match, not new
    assert p1.id == p2.id
    assert {s.source for s in p2.sources} == {"realtor", "zillow"}
    assert p2.status == "pending"              # latest sync wins for facts
    assert p2.origin == "region_search"        # primary provenance preserved


def test_same_source_reingest_updates_not_duplicates(db_session):
    r = _nl(source_id="R9", address="9 Oak Rd", zip="95448", latitude=38.6, longitude=-122.9, beds=4, price=800000)
    p1, c1 = _upsert(db_session, "realtor", r, download=False)
    r2 = _nl(source_id="R9", address="9 Oak Rd", zip="95448", latitude=38.6, longitude=-122.9, beds=4, price=750000)
    p2, c2 = _upsert(db_session, "realtor", r2, download=False)
    db_session.commit()
    assert c1 is True and c2 is False
    assert p1.id == p2.id
    assert p2.price == 750000
    assert len(p2.sources) == 1               # one source link, not duplicated


def test_distinct_homes_do_not_merge(db_session):
    a = _nl(source_id="A", address="1 First St", zip="95404", latitude=38.40, longitude=-122.70)
    b = _nl(source_id="B", address="2 Second Ave", zip="95404", latitude=38.50, longitude=-122.85)
    pa, _ = _upsert(db_session, "realtor", a, download=False)
    pb, _ = _upsert(db_session, "realtor", b, download=False)
    db_session.commit()
    assert pa.id != pb.id


def test_coord_fallback_respects_beds(db_session):
    """Coordinate-fallback match (distinct address text, identical point) only
    merges when bed counts agree — guards condo/apartment buildings."""
    a = _nl(source_id="U1", address="500 First St", zip="95401", latitude=38.44, longitude=-122.71, beds=2)
    pa, _ = _upsert(db_session, "realtor", a, download=False)
    # Same point, different address text, DIFFERENT beds → not a match.
    b = _nl(source_id="U2", address="999 Second Ave", zip="95401", latitude=38.44, longitude=-122.71, beds=3)
    pb, _ = _upsert(db_session, "zillow", b, download=False)
    # Same point, different address text, SAME beds → coordinate match.
    c = _nl(source_id="U3", address="777 Third Blvd", zip="95401", latitude=38.44, longitude=-122.71, beds=2)
    pc, _ = _upsert(db_session, "zillow", c, download=False)
    db_session.commit()
    assert pb.id != pa.id   # beds differ → kept separate
    assert pc.id == pa.id   # same point + beds → merged