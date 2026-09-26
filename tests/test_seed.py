from app.seed import ADMIN_EMAIL, ADMIN_PASSWORD, seed


def test_seed_is_repeatable_and_admin_can_log_in(client, db):
    seed(db)
    seed(db)  # second run must not duplicate or fail

    res = client.post("/auth/login/", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD})
    assert res.status_code == 200
    me = client.get("/auth/me/", headers={"Authorization": f"Bearer {res.json()['access_token']}"}).json()
    assert me["is_admin"] is True
    assert client.get("/centres/").json()["total"] == 3
