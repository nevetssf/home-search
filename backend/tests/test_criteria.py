"""Tests for the flexible typed-criteria system — the core of the data model."""


def _make_criterion(client, **overrides):
    payload = {
        "name": "Vineyard?",
        "value_type": "boolean",
        "is_subjective": False,
    }
    payload.update(overrides)
    r = client.post("/criteria", json=payload)
    assert r.status_code == 201, r.text
    return r.json()


def test_create_criterion_validation(client):
    # rating requires a scale
    r = client.post(
        "/criteria",
        json={"name": "Feel", "value_type": "rating", "is_subjective": True},
    )
    assert r.status_code == 400
    # enum requires options
    r = client.post("/criteria", json={"name": "Roof", "value_type": "enum"})
    assert r.status_code == 400


def test_objective_value_is_shared(client, make_property):
    prop = make_property()
    crit = _make_criterion(client, name="Olive trees", value_type="number", unit="trees")
    client.put(
        f"/properties/{prop['id']}/criteria/{crit['id']}",
        json={"value_number": 12},
    )
    data = client.get(f"/properties/{prop['id']}/criteria").json()
    assert len(data["objective"]) == 1
    assert data["objective"][0]["value_number"] == 12
    assert data["objective"][0]["user_id"] == 0  # OBJECTIVE_USER_ID sentinel


def test_subjective_rating_is_per_user_and_scores(client, make_property):
    prop = make_property()
    crit = _make_criterion(
        client,
        name="Feel of the house",
        value_type="rating",
        is_subjective=True,
        scale_min=1,
        scale_max=5,
        weight=2.0,
    )
    # current user rates 4/5
    client.put(
        f"/properties/{prop['id']}/criteria/{crit['id']}",
        json={"value_number": 4},
    )
    data = client.get(f"/properties/{prop['id']}/criteria").json()
    assert len(data["my_ratings"]) == 1
    # normalized (4-1)/(5-1) = 0.75
    assert abs(data["aggregate_ratings"][str(crit["id"])] - 0.75) < 1e-9
    assert abs(data["overall_score"] - 0.75) < 1e-9


def test_rating_out_of_range_rejected(client, make_property):
    prop = make_property()
    crit = _make_criterion(
        client, name="Feel", value_type="rating", is_subjective=True,
        scale_min=1, scale_max=5,
    )
    r = client.put(
        f"/properties/{prop['id']}/criteria/{crit['id']}", json={"value_number": 9}
    )
    assert r.status_code == 400


def test_enum_value_must_be_in_options(client, make_property):
    prop = make_property()
    crit = _make_criterion(
        client, name="Roof", value_type="enum", options=["tile", "shingle"]
    )
    ok = client.put(
        f"/properties/{prop['id']}/criteria/{crit['id']}", json={"value_text": "tile"}
    )
    assert ok.status_code == 200
    bad = client.put(
        f"/properties/{prop['id']}/criteria/{crit['id']}", json={"value_text": "thatch"}
    )
    assert bad.status_code == 400


def test_setting_value_twice_updates_not_duplicates(client, make_property):
    prop = make_property()
    crit = _make_criterion(client, name="ADU?", value_type="boolean")
    client.put(f"/properties/{prop['id']}/criteria/{crit['id']}", json={"value_bool": True})
    client.put(f"/properties/{prop['id']}/criteria/{crit['id']}", json={"value_bool": False})
    data = client.get(f"/properties/{prop['id']}/criteria").json()
    assert len(data["objective"]) == 1
    assert data["objective"][0]["value_bool"] is False


def test_filter_properties_by_criterion(client, make_property):
    p1 = make_property()
    p2 = make_property()
    crit = _make_criterion(client, name="Acres", value_type="number", unit="acres")
    client.put(f"/properties/{p1['id']}/criteria/{crit['id']}", json={"value_number": 10})
    client.put(f"/properties/{p2['id']}/criteria/{crit['id']}", json={"value_number": 2})
    # criterion[<id>]=gte:5  → only p1
    r = client.get("/properties", params={f"criterion[{crit['id']}]": "gte:5"})
    ids = [p["id"] for p in r.json()]
    assert ids == [p1["id"]]


def test_boolean_criterion_filter(client, make_property):
    p1 = make_property()
    make_property()
    crit = _make_criterion(client, name="Vineyard?", value_type="boolean")
    client.put(f"/properties/{p1['id']}/criteria/{crit['id']}", json={"value_bool": True})
    r = client.get("/properties", params={f"criterion[{crit['id']}]": "true"})
    assert [p["id"] for p in r.json()] == [p1["id"]]


def test_list_with_criteria_attaches_columns_and_score(client, make_property):
    prop = make_property()
    acres = _make_criterion(client, name="Acres", value_type="number", unit="acres")
    feel = _make_criterion(
        client, name="Feel", value_type="rating", is_subjective=True,
        scale_min=1, scale_max=5,
    )
    client.put(f"/properties/{prop['id']}/criteria/{acres['id']}", json={"value_number": 8})
    client.put(f"/properties/{prop['id']}/criteria/{feel['id']}", json={"value_number": 4})

    rows = client.get("/properties", params={"with_criteria": True}).json()
    row = next(r for r in rows if r["id"] == prop["id"])
    # objective value shown directly; subjective shown as household mean (raw)
    assert row["criteria"][str(acres["id"])] == 8
    assert row["criteria"][str(feel["id"])] == 4
    assert abs(row["overall_score"] - 0.75) < 1e-9


def test_list_without_criteria_flag_omits_them(client, make_property):
    make_property()
    rows = client.get("/properties").json()
    assert rows[0]["criteria"] is None
    assert rows[0]["overall_score"] is None


def test_no_subjective_ratings_gives_null_score(client, make_property):
    prop = make_property()
    crit = _make_criterion(client, name="Acres", value_type="number")
    client.put(f"/properties/{prop['id']}/criteria/{crit['id']}", json={"value_number": 5})
    data = client.get(f"/properties/{prop['id']}/criteria").json()
    assert data["overall_score"] is None
