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


def test_redfin_url_ingest_via_scrape(client, monkeypatch):
    html = """
    <script type="application/ld+json">
    {"@type":"SingleFamilyResidence",
     "address":{"streetAddress":"1 Oak Rd","addressLocality":"Healdsburg",
       "addressRegion":"CA","postalCode":"95448"},
     "geo":{"latitude":38.6,"longitude":-122.9},"offers":{"price":1500000}}
    </script>
    """
    monkeypatch.setattr(scrape, "fetch_html", lambda url: html)
    r = client.post(
        "/ingest/url",
        json={"url": "https://www.redfin.com/CA/Healdsburg/1-Oak-Rd/home/123"},
        params={"download_photos": False},
    )
    assert r.status_code == 200, r.text
    detail = client.get(f"/properties/{r.json()['property_ids'][0]}").json()
    assert detail["source"] == "redfin"
    assert detail["city"] == "Healdsburg"
    assert detail["price"] == 1500000


def test_scrape_blocked_without_api_key_returns_502(client, monkeypatch):
    """Zillow blocked + no RAPIDAPI key → 502 (caller falls back to manual)."""
    def blocked(url):
        raise scrape.ScrapeBlocked("bot wall")

    monkeypatch.setattr(scrape, "fetch_html", blocked)
    r = client.post(
        "/ingest/url", json={"url": "https://www.zillow.com/homedetails/x/1_zpid/"}
    )
    assert r.status_code == 502


def test_unknown_host_rejected(client):
    r = client.post("/ingest/url", json={"url": "https://example.com/listing/1"})
    assert r.status_code == 400
