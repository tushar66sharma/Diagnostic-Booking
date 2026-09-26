import pytest

from tests.conftest import auth_headers, make_offering

CENTRE = {"name": "Metro Labs", "city": "Mumbai", "address": "12 Linking Road"}


def test_admin_can_build_catalogue_and_public_can_read_it(client, admin):
    h = auth_headers(admin)
    centre = client.post("/centres/", json=CENTRE, headers=h).json()
    test = client.post("/tests/", json={"name": "Lipid Profile", "description": "Cholesterol panel"}, headers=h).json()

    res = client.put(f"/centres/{centre['id']}/tests/{test['id']}/", json={"price": "799.50"}, headers=h)
    assert res.status_code == 200
    assert res.json()["price"] == "799.50"

    detail = client.get(f"/centres/{centre['id']}/")  # no auth needed
    assert detail.status_code == 200
    assert detail.json()["tests"] == [
        {"test_id": test["id"], "test_name": "Lipid Profile", "description": "Cholesterol panel",
         "price": "799.50", "is_active": True}
    ]


def test_put_offering_is_idempotent_and_updates_price(client, admin, offering):
    h = auth_headers(admin)
    url = f"/centres/{offering.centre_id}/tests/{offering.test_id}/"

    client.put(url, json={"price": "650"}, headers=h)
    client.put(url, json={"price": "650"}, headers=h)

    tests = client.get(f"/centres/{offering.centre_id}/").json()["tests"]
    assert len(tests) == 1
    assert tests[0]["price"] == "650.00"


def test_deactivated_offering_is_hidden(client, admin, offering):
    client.put(
        f"/centres/{offering.centre_id}/tests/{offering.test_id}/",
        json={"price": "500", "is_active": False},
        headers=auth_headers(admin),
    )

    assert client.get(f"/centres/{offering.centre_id}/").json()["tests"] == []
    assert client.get("/centres/", params={"test_id": offering.test_id}).json()["total"] == 0


def test_same_test_can_have_different_prices_at_different_centres(client, db):
    a = make_offering(db, price="400", centre_name="A Labs")
    b = make_offering(db, price="900", centre_name="B Labs")

    assert client.get(f"/centres/{a.centre_id}/").json()["tests"][0]["price"] == "400.00"
    assert client.get(f"/centres/{b.centre_id}/").json()["tests"][0]["price"] == "900.00"


def test_list_centres_filters_and_paginates(client, db):
    make_offering(db, centre_name="P1", city="Pune")
    make_offering(db, centre_name="P2", city="pune")
    make_offering(db, centre_name="D1", city="Delhi", test_name="Thyroid Profile")

    by_city = client.get("/centres/", params={"city": "PUNE"}).json()
    assert by_city["total"] == 2

    page2 = client.get("/centres/", params={"page": 2, "page_size": 2}).json()
    assert page2["total"] == 3
    assert [c["name"] for c in page2["items"]] == ["D1"]


@pytest.mark.parametrize("params", [{"page": 0}, {"page_size": 101}, {"page": "x"}])
def test_list_centres_rejects_bad_pagination(client, params):
    assert client.get("/centres/", params=params).status_code == 422


def test_unknown_centre_returns_404(client):
    assert client.get("/centres/999/").status_code == 404


def test_offering_for_unknown_centre_or_test_returns_404(client, admin, offering):
    h = auth_headers(admin)

    assert client.put(f"/centres/999/tests/{offering.test_id}/", json={"price": "1"}, headers=h).status_code == 404
    assert client.put(f"/centres/{offering.centre_id}/tests/999/", json={"price": "1"}, headers=h).status_code == 404


@pytest.mark.parametrize("price", ["0", "-10", "12.345", "abc"])
def test_offering_rejects_invalid_price(client, admin, offering, price):
    res = client.put(
        f"/centres/{offering.centre_id}/tests/{offering.test_id}/", json={"price": price}, headers=auth_headers(admin)
    )
    assert res.status_code == 422


def test_duplicate_test_name_conflicts(client, admin):
    h = auth_headers(admin)
    client.post("/tests/", json={"name": "CBC"}, headers=h)

    assert client.post("/tests/", json={"name": "CBC"}, headers=h).status_code == 409


def test_non_admin_cannot_modify_catalogue(client, user, offering):
    h = auth_headers(user)

    assert client.post("/centres/", json=CENTRE, headers=h).status_code == 403
    assert client.post("/tests/", json={"name": "X"}, headers=h).status_code == 403
    assert (
        client.put(f"/centres/{offering.centre_id}/tests/{offering.test_id}/", json={"price": "1"}, headers=h)
        .status_code == 403
    )


def test_anonymous_cannot_modify_catalogue(client):
    assert client.post("/centres/", json=CENTRE).status_code == 401


def test_admin_can_partially_update_centre(client, admin, offering):
    res = client.patch(f"/centres/{offering.centre_id}/", json={"city": "  Mumbai "}, headers=auth_headers(admin))

    assert res.status_code == 200
    assert res.json()["city"] == "Mumbai"
    assert res.json()["name"] == "City Diagnostics"  # untouched
    assert client.get("/centres/", params={"city": "mumbai"}).json()["total"] == 1


@pytest.mark.parametrize("body", [{}, {"name": None}, {"address": "   "}, {"name": "x" * 201}])
def test_centre_update_rejects_invalid_body(client, admin, offering, body):
    res = client.patch(f"/centres/{offering.centre_id}/", json=body, headers=auth_headers(admin))
    assert res.status_code == 422


def test_centre_update_unknown_centre_is_404(client, admin):
    assert client.patch("/centres/999/", json={"name": "X"}, headers=auth_headers(admin)).status_code == 404


def test_non_admin_cannot_update_centre(client, user, offering):
    res = client.patch(f"/centres/{offering.centre_id}/", json={"name": "Hacked"}, headers=auth_headers(user))

    assert res.status_code == 403
    assert client.get(f"/centres/{offering.centre_id}/").json()["name"] == "City Diagnostics"
