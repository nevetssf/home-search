"""Ingestion tests: Zillow normalization, Redfin CSV parsing, and the URL ingest
endpoint with the Zillow client monkeypatched (no network)."""
from app.services import redfin_csv
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


def test_zillow_url_ingest_endpoint(client, monkeypatch):
    """Monkeypatch the client so no network call happens; verify upsert + cache."""
    from app.routers import ingest as ingest_router

    fake_payload = {
        "zpid": 42,
        "url": "https://zillow.com/homedetails/x/42_zpid/",
        "address": {"streetAddress": "9 Hill Rd", "city": "Glen Ellen", "state": "CA"},
        "price": 990000,
        "bedrooms": 2,
        "homeStatus": "FOR_SALE",
        "photos": [],
    }

    def fake_fetch(self, url):
        return fake_payload

    monkeypatch.setattr(ingest_router.ZillowClient, "fetch_by_url", fake_fetch)

    r = client.post(
        "/ingest/zillow/url",
        json={"url": "https://zillow.com/homedetails/x/42_zpid/"},
        params={"download_photos": False},
    )
    assert r.status_code == 200, r.text
    result = r.json()
    assert result["created"] == 1
    pid = result["property_ids"][0]

    detail = client.get(f"/properties/{pid}").json()
    assert detail["city"] == "Glen Ellen"
    assert detail["source"] == "zillow"
    assert detail["raw_payload"]["zpid"] == 42  # raw response cached

    # Re-ingest updates rather than duplicates.
    r2 = client.post(
        "/ingest/zillow/url",
        json={"url": "https://zillow.com/homedetails/x/42_zpid/"},
        params={"download_photos": False},
    )
    assert r2.json()["updated"] == 1


def test_ingest_without_key_returns_503(client):
    r = client.post("/ingest/zillow/url", json={"url": "https://zillow.com/x/1_zpid/"})
    assert r.status_code == 503
