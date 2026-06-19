def test_create_records_status_history(client, make_property):
    prop = make_property()
    r = client.get(f"/properties/{prop['id']}/status-history")
    assert r.status_code == 200
    history = r.json()
    assert len(history) == 1
    assert history[0]["status"] == "for_sale"


def test_status_change_appends_history(client, make_property):
    prop = make_property()
    client.patch(f"/properties/{prop['id']}", json={"status": "pending"})
    client.patch(f"/properties/{prop['id']}", json={"status": "pending"})  # no-op
    client.patch(f"/properties/{prop['id']}", json={"status": "sold"})
    history = client.get(f"/properties/{prop['id']}/status-history").json()
    assert [h["status"] for h in history] == ["for_sale", "pending", "sold"]


def test_invalid_status_rejected(client, make_property):
    prop = make_property()
    r = client.patch(f"/properties/{prop['id']}", json={"status": "nonsense"})
    assert r.status_code == 400


def test_filter_by_price_and_beds(client, make_property):
    make_property(price=500000, beds=2)
    make_property(price=1500000, beds=4)
    r = client.get("/properties", params={"min_price": 1000000, "beds": 3})
    assert r.status_code == 200
    results = r.json()
    assert len(results) == 1
    assert results[0]["price"] == 1500000


def test_bbox_filter(client, make_property):
    make_property(latitude=38.4, longitude=-122.8)  # inside
    make_property(latitude=40.0, longitude=-120.0)  # outside
    r = client.get("/properties", params={"bbox": "-123,38,-122,39"})
    assert len(r.json()) == 1


def test_archive_hides_from_default_list(client, make_property):
    prop = make_property()
    client.patch(f"/properties/{prop['id']}", json={"archived": True})
    assert len(client.get("/properties").json()) == 0
    assert len(client.get("/properties", params={"archived": True}).json()) == 1


def test_tags_and_notes(client, make_property):
    prop = make_property()
    tag = client.post("/tags", json={"name": "favorite", "color": "#f00"}).json()
    client.put(f"/properties/{prop['id']}/tags", json=[tag["id"]])
    detail = client.get(f"/properties/{prop['id']}").json()
    assert detail["tags"][0]["name"] == "favorite"

    client.post(f"/properties/{prop['id']}/notes", json={"body": "great light"})
    notes = client.get(f"/properties/{prop['id']}/notes").json()
    assert notes[0]["body"] == "great light"


def test_filter_by_tag(client, make_property):
    p1 = make_property()
    make_property()
    tag = client.post("/tags", json={"name": "vineyard"}).json()
    client.put(f"/properties/{p1['id']}/tags", json=[tag["id"]])
    r = client.get("/properties", params={"tags": "vineyard"})
    assert len(r.json()) == 1
    assert r.json()[0]["id"] == p1["id"]


def test_edit_and_delete_note(client, make_property):
    prop = make_property()
    note = client.post(f"/properties/{prop['id']}/notes", json={"body": "first"}).json()

    # edit
    r = client.patch(f"/properties/{prop['id']}/notes/{note['id']}", json={"body": "edited"})
    assert r.status_code == 200
    assert r.json()["body"] == "edited"
    assert client.get(f"/properties/{prop['id']}/notes").json()[0]["body"] == "edited"

    # delete
    assert client.delete(f"/properties/{prop['id']}/notes/{note['id']}").status_code == 204
    assert client.get(f"/properties/{prop['id']}/notes").json() == []

    # editing/deleting a missing note → 404
    assert client.patch(f"/properties/{prop['id']}/notes/{note['id']}", json={"body": "x"}).status_code == 404
    assert client.delete(f"/properties/{prop['id']}/notes/{note['id']}").status_code == 404


def test_sort_desc(client, make_property):
    make_property(price=500000)
    make_property(price=900000)
    r = client.get("/properties", params={"sort": "-price"})
    prices = [p["price"] for p in r.json()]
    assert prices == sorted(prices, reverse=True)
