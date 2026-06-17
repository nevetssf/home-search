import io


def test_upload_list_and_fetch_media(client, make_property):
    prop = make_property()
    files = {"file": ("photo.jpg", io.BytesIO(b"fake-jpeg-bytes"), "image/jpeg")}
    data = {"property_id": str(prop["id"]), "kind": "photo", "caption": "front"}
    r = client.post("/media", data=data, files=files)
    assert r.status_code == 201, r.text
    media = r.json()
    assert media["origin"] == "upload"
    assert media["url"] == f"/media/{media['id']}/file"

    listing = client.get("/media", params={"property_id": prop["id"]}).json()
    assert len(listing) == 1

    # file streams back the same bytes
    fr = client.get(media["url"])
    assert fr.status_code == 200
    assert fr.content == b"fake-jpeg-bytes"


def test_delete_media(client, make_property):
    prop = make_property()
    files = {"file": ("p.jpg", io.BytesIO(b"x"), "image/jpeg")}
    media = client.post(
        "/media", data={"property_id": str(prop["id"])}, files=files
    ).json()
    assert client.delete(f"/media/{media['id']}").status_code == 204
    assert client.get(f"/media/{media['id']}/file").status_code == 404


def test_storage_key_namespaced_by_property(client, make_property):
    from app.services.storage import make_key

    key = make_key(42, "vacation.JPG")
    assert key.startswith("properties/42/")
    assert key.endswith(".jpg")
