"""Ingestion tests: Zillow normalization, Redfin CSV parsing, and the URL ingest
endpoint with the Zillow client monkeypatched (no network)."""
from app.services import redfin_csv, scrape
from app.services.zillow import extract_zpid, normalize


def test_extract_zpid():
    url = "https://www.zillow.com/homedetails/1-Vine-St/12345678_zpid/"
    assert extract_zpid(url) == "12345678"
    assert extract_zpid("https://www.zillow.com/nope/") is None


def test_normalize_nested_address_and_status():
    payload = {
        "zpid": 999,
        "url": "https://zillow.com/x/999_zpid/",
        "address": {
            "streetAddress": "1 Vine St",
            "city": "Sebastopol",
            "state": "CA",
            "zipcode": "95472",
        },
        "price": 1250000,
        "bedrooms": 3,
        "bathrooms": 2.5,
        "livingArea": 2100,
        "homeStatus": "PENDING",
        "yearBuilt": 1998,
        "latitude": 38.4,
        "longitude": -122.8,
        "photos": [{"url": "http://img/1.jpg"}, "http://img/2.jpg"],
    }
    n = normalize(payload)
    assert n.source_id == "999"
    assert n.city == "Sebastopol"
    assert n.status == "pending"
    assert n.beds == 3 and n.baths == 2.5
    assert n.year_built == 1998
    assert n.photo_urls == ["http://img/1.jpg", "http://img/2.jpg"]


def test_normalize_is_defensive_on_thin_payload():
    n = normalize({"zpid": 5})
    assert n.source_id == "5"
    assert n.status == "for_sale"  # default
    assert n.price is None


def test_redfin_csv_parse():
    csv_bytes = (
        b"ADDRESS,CITY,STATE OR PROVINCE,ZIP OR POSTAL CODE,PRICE,BEDS,BATHS,"
        b"SQUARE FEET,LOT SIZE,YEAR BUILT,PROPERTY TYPE,LATITUDE,LONGITUDE,MLS#,URL\n"
        b"1 Oak Rd,Healdsburg,CA,95448,\"1,500,000\",4,3,2500,1.5,2005,"
        b"Single Family Residential,38.6,-122.9,ML123,http://redfin/x\n"
    )
    rows = redfin_csv.parse_csv(csv_bytes)
    assert len(rows) == 1
    row = rows[0]
    assert row.city == "Healdsburg"
    assert row.price == 1500000
    assert row.beds == 4
    assert row.lot_size == 1.5
    assert row.source_id == "ML123"


# ── Direct scraper (no network: fetch_html is monkeypatched with canned HTML) ──
def test_detect_source():
    assert scrape.detect_source("https://www.zillow.com/homedetails/x/42_zpid/") == "zillow"
    assert scrape.detect_source("https://www.redfin.com/CA/x/home/123") == "redfin"
    assert scrape.detect_source("https://example.com/x") is None


def test_parse_jsonld_extracts_core_fields():
    html = """
    <script type="application/ld+json">
    {"@type":"SingleFamilyResidence",
     "address":{"@type":"PostalAddress","streetAddress":"1 Oak Rd",
       "addressLocality":"Healdsburg","addressRegion":"CA","postalCode":"95448"},
     "geo":{"latitude":38.6,"longitude":-122.9},
     "offers":{"price":1500000},
     "image":["http://img/a.jpg","http://img/b.jpg"]}
    </script>
    """
    ld = scrape.parse_jsonld(html)
    assert ld["street"] == "1 Oak Rd"
    assert ld["city"] == "Healdsburg"
    assert ld["price"] == 1500000
    assert ld["latitude"] == 38.6
    assert ld["photos"] == ["http://img/a.jpg", "http://img/b.jpg"]


def _zillow_next_data_html():
    import json as _json
    prop = {
        "zpid": 42, "streetAddress": "9 Hill Rd", "city": "Glen Ellen",
        "state": "CA", "zipcode": "95442", "price": 990000, "bedrooms": 2,
        "bathrooms": 2, "homeStatus": "FOR_SALE", "latitude": 38.3,
        "longitude": -122.5, "hdpUrl": "/homedetails/x/42_zpid/",
    }
    cache = _json.dumps({"q": {"property": prop}})
    next_data = {"props": {"pageProps": {"componentProps": {"gdpClientCache": cache}}}}
    return (
        '<html><body><script id="__NEXT_DATA__" type="application/json">'
        + _json.dumps(next_data)
        + "</script></body></html>"
    )


def test_zillow_url_ingest_via_scrape(client, monkeypatch):
    """Scrape path (no API key): canned __NEXT_DATA__ HTML, no network."""
    monkeypatch.setattr(scrape, "fetch_html", lambda url: _zillow_next_data_html())

    r = client.post(
        "/ingest/url",
        json={"url": "https://www.zillow.com/homedetails/x/42_zpid/"},
        params={"download_photos": False},
    )
    assert r.status_code == 200, r.text
    pid = r.json()["property_ids"][0]
    detail = client.get(f"/properties/{pid}").json()
    assert detail["city"] == "Glen Ellen"
    assert detail["beds"] == 2
    assert detail["source"] == "zillow"
    assert detail["raw_payload"]["_scraped"] == "next_data"

    # Re-ingest updates rather than duplicates.
    r2 = client.post(
        "/ingest/url",
        json={"url": "https://www.zillow.com/homedetails/x/42_zpid/"},
        params={"download_photos": False},
    )
    assert r2.json()["updated"] == 1


# A real Redfin page interleaves the subject RealEstateListing with several
# "similar homes" SingleFamilyResidence blocks at *other* addresses. The decoy
# below (San Francisco) must NOT win — that was the Santa-Rosa→SF bug.
_REDFIN_HTML = """
<script type="application/ld+json">
{"@type":"SingleFamilyResidence",
 "address":{"streetAddress":"568 6th Ave","addressLocality":"San Francisco",
   "addressRegion":"CA","postalCode":"94118"}}
</script>
<script type="application/ld+json">
{"@context":"https://schema.org","@type":["Product","RealEstateListing"],
 "name":"1 Oak Rd","description":"Lovely.",
 "url":"https://www.redfin.com/CA/Healdsburg/1-Oak-Rd-95448/home/123",
 "image":[{"@type":"ImageObject","url":"https://img/redfin/a.jpg"}],
 "offers":{"@type":"Offer","price":1500000,"availability":"https://schema.org/InStock"},
 "mainEntity":{"@type":"SingleFamilyResidence","numberOfBedrooms":4,
   "geo":{"latitude":38.6,"longitude":-122.9}}}
</script>
"""


def test_redfin_url_ingest_via_scrape(client, monkeypatch):
    monkeypatch.setattr(scrape, "fetch_html", lambda url: _REDFIN_HTML)
    r = client.post(
        "/ingest/url",
        json={"url": "https://www.redfin.com/CA/Healdsburg/1-Oak-Rd-95448/home/123"},
        params={"download_photos": False},
    )
    assert r.status_code == 200, r.text
    detail = client.get(f"/properties/{r.json()['property_ids'][0]}").json()
    assert detail["source"] == "redfin"
    assert detail["address"] == "1 Oak Rd"
    assert detail["city"] == "Healdsburg"   # from URL slug, NOT the SF decoy
    assert detail["state"] == "CA"
    assert detail["zip"] == "95448"
    assert detail["price"] == 1500000
    assert detail["beds"] == 4              # enriched from mainEntity


def test_redfin_scrape_unit_ignores_similar_homes(monkeypatch):
    """Regression: the similar-homes SingleFamilyResidence block is ignored."""
    monkeypatch.setattr(scrape, "fetch_html", lambda url: _REDFIN_HTML)
    listing = scrape.scrape_redfin(
        "https://www.redfin.com/CA/Healdsburg/1-Oak-Rd-95448/home/123"
    )
    assert listing.city == "Healdsburg"
    assert listing.address == "1 Oak Rd"
    assert listing.latitude == 38.6


_SANTA_ROSA_SLUG = {
    "zpid": "12345", "street": "7455 Foothill Ranch Rd", "city": "Santa Rosa",
    "state": "CA", "zip": "95404", "lat": 38.44, "lng": -122.71,
}
_SR_URL = "https://www.zillow.com/homedetails/7455-Foothill-Ranch-Rd-Santa-Rosa-CA-95404/12345_zpid/"


def test_parse_zillow_url_resolves_multiword_city(monkeypatch):
    # Avoid pgeocode network: stub the ZIP lookup.
    monkeypatch.setattr(scrape, "_zip_lookup", lambda z: {
        "city": "Santa Rosa", "state": "CA", "lat": 38.44, "lng": -122.71,
    })
    parsed = scrape.parse_zillow_url(_SR_URL)
    assert parsed["zpid"] == "12345"
    assert parsed["zip"] == "95404"
    assert parsed["city"] == "Santa Rosa"   # multi-word, from ZIP
    assert parsed["street"] == "7455 Foothill Ranch Rd"  # city words stripped


def test_zillow_blocked_falls_back_to_slug_stub(client, monkeypatch):
    """Blocked + no API key + no Realtor match → accurate address-only stub."""
    from app.services import realtor as realtor_mod

    monkeypatch.setattr(scrape, "fetch_html", lambda url: (_ for _ in ()).throw(
        scrape.ScrapeBlocked("bot wall")))
    monkeypatch.setattr(scrape, "parse_zillow_url", lambda url: dict(_SANTA_ROSA_SLUG))
    monkeypatch.setattr(realtor_mod, "search", lambda **k: [])  # no Realtor match

    r = client.post("/ingest/url", json={"url": _SR_URL}, params={"download_photos": False})
    assert r.status_code == 200, r.text
    detail = client.get(f"/properties/{r.json()['property_ids'][0]}").json()
    assert detail["source"] == "zillow"
    assert detail["city"] == "Santa Rosa"
    assert detail["address"] == "7455 Foothill Ranch Rd"
    assert detail["zip"] == "95404"
    assert detail["price"] is None  # stub: address only, user/API fills the rest


def test_zillow_blocked_enriches_from_realtor_on_match(client, monkeypatch):
    """Blocked + a Realtor result whose zip+house number match → full data."""
    from app.services import realtor as realtor_mod
    from app.services.zillow import NormalizedListing

    monkeypatch.setattr(scrape, "fetch_html", lambda url: (_ for _ in ()).throw(
        scrape.ScrapeBlocked("bot wall")))
    monkeypatch.setattr(scrape, "parse_zillow_url", lambda url: dict(_SANTA_ROSA_SLUG))

    match = NormalizedListing(
        source_id="R1", source_url="https://realtor.com/x",
        address="7455 Foothill Ranch Rd", city="Santa Rosa", state="CA",
        zip="95404", price=2000000, beds=4,
    )
    # Include a decoy with a different house number to prove the guard works.
    decoy = NormalizedListing(source_id="R2", source_url=None, address="999 Other Rd", zip="95404")
    monkeypatch.setattr(realtor_mod, "search", lambda **k: [decoy, match])

    r = client.post("/ingest/url", json={"url": _SR_URL}, params={"download_photos": False})
    assert r.status_code == 200, r.text
    detail = client.get(f"/properties/{r.json()['property_ids'][0]}").json()
    assert detail["source"] == "realtor"
    assert detail["price"] == 2000000
    assert detail["beds"] == 4
    assert detail["source_url"] == _SR_URL  # keeps the pasted Zillow link


def test_zillow_unparseable_url_returns_502(client, monkeypatch):
    monkeypatch.setattr(scrape, "fetch_html", lambda url: (_ for _ in ()).throw(
        scrape.ScrapeBlocked("bot wall")))
    monkeypatch.setattr(scrape, "parse_zillow_url", lambda url: None)
    r = client.post("/ingest/url", json={"url": "https://www.zillow.com/b/nonsense/"})
    assert r.status_code == 502


def test_unknown_host_rejected(client):
    r = client.post("/ingest/url", json={"url": "https://example.com/listing/1"})
    assert r.status_code == 400
