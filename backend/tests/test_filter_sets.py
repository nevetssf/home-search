"""Named filter sets CRUD — per-user, name-unique, opaque JSON payload."""
from app.models import FilterSet


def test_create_list_and_payload_roundtrip(client):
    payload = {"value_filters": {"price": ">500000", "beds": ">=3"},
               "filter_regions": [{"kind": "circle", "center": [38.4, -122.7], "radius_mi": 5}]}
    r = client.post("/filter-sets", json={"name": "Wine country", "payload": payload})
    assert r.status_code == 201, r.text
    fs = r.json()
    assert fs["name"] == "Wine country"
    assert fs["payload"]["value_filters"]["price"] == ">500000"

    listed = client.get("/filter-sets").json()
    assert [s["name"] for s in listed] == ["Wine country"]
    assert listed[0]["payload"]["filter_regions"][0]["kind"] == "circle"


def test_duplicate_name_rejected(client):
    client.post("/filter-sets", json={"name": "dup"})
    r = client.post("/filter-sets", json={"name": "dup"})
    assert r.status_code == 409


def test_rename_and_update_payload(client):
    fs = client.post("/filter-sets", json={"name": "A", "payload": {"value_filters": {}}}).json()
    r = client.patch(f"/filter-sets/{fs['id']}", json={
        "name": "B", "payload": {"value_filters": {"city": "Sonoma"}, "filter_regions": []},
    })
    assert r.status_code == 200
    assert r.json()["name"] == "B"
    assert r.json()["payload"]["value_filters"]["city"] == "Sonoma"


def test_rename_clash_rejected(client):
    client.post("/filter-sets", json={"name": "one"})
    two = client.post("/filter-sets", json={"name": "two"}).json()
    r = client.patch(f"/filter-sets/{two['id']}", json={"name": "one"})
    assert r.status_code == 409


def test_delete(client):
    fs = client.post("/filter-sets", json={"name": "temp"}).json()
    assert client.delete(f"/filter-sets/{fs['id']}").status_code == 204
    assert client.get("/filter-sets").json() == []
    # deleting a non-existent set → 404
    assert client.delete(f"/filter-sets/{fs['id']}").status_code == 404


def test_sets_are_per_user(client, db_session):
    """A different user's set must not appear or be editable."""
    client.post("/filter-sets", json={"name": "mine"})
    # Insert a set owned by some other user directly.
    db_session.add(FilterSet(user_id=9999, name="theirs", payload={}))
    db_session.commit()
    other = db_session.query(FilterSet).filter(FilterSet.user_id == 9999).first()

    names = [s["name"] for s in client.get("/filter-sets").json()]
    assert names == ["mine"]                       # theirs not listed
    assert client.patch(f"/filter-sets/{other.id}", json={"name": "x"}).status_code == 404
    assert client.delete(f"/filter-sets/{other.id}").status_code == 404
