from datetime import datetime, timedelta, timezone

import jwt
import pytest

from app.config import settings
from tests.conftest import auth_headers

SIGNUP = {"email": "Asha@Example.com", "password": "Secret123", "full_name": "Asha Rao"}


def test_signup_creates_user_without_exposing_password(client):
    res = client.post("/auth/signup/", json=SIGNUP)

    assert res.status_code == 201
    body = res.json()
    assert body["email"] == "asha@example.com"  # normalised
    assert body["is_admin"] is False
    assert "password" not in body and "password_hash" not in body


def test_signup_duplicate_email_is_case_insensitive(client):
    client.post("/auth/signup/", json=SIGNUP)
    res = client.post("/auth/signup/", json={**SIGNUP, "email": "ASHA@example.com"})

    assert res.status_code == 409


def test_signup_cannot_make_itself_admin(client):
    res = client.post("/auth/signup/", json={**SIGNUP, "is_admin": True})

    assert res.status_code == 201
    assert res.json()["is_admin"] is False


@pytest.mark.parametrize(
    "payload",
    [
        {**SIGNUP, "email": "not-an-email"},
        {**SIGNUP, "password": "short1"},
        {**SIGNUP, "password": "onlyletters"},
        {**SIGNUP, "full_name": "   "},
        {"email": "a@b.com"},
    ],
)
def test_signup_rejects_invalid_input(client, payload):
    assert client.post("/auth/signup/", json=payload).status_code == 422


def test_login_returns_token_that_authenticates(client):
    client.post("/auth/signup/", json=SIGNUP)

    res = client.post("/auth/login/", json={"email": "asha@example.com", "password": "Secret123"})

    assert res.status_code == 200
    token = res.json()["access_token"]
    me = client.get("/auth/me/", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200
    assert me.json()["email"] == "asha@example.com"


@pytest.mark.parametrize("email,password", [("asha@example.com", "Wrong1234"), ("nobody@example.com", "Secret123")])
def test_login_with_bad_credentials_gives_same_401(client, email, password):
    client.post("/auth/signup/", json=SIGNUP)

    res = client.post("/auth/login/", json={"email": email, "password": password})

    assert res.status_code == 401
    assert res.json()["detail"] == "Invalid email or password"


def test_login_is_rate_limited(client):
    bad = {"email": "x@example.com", "password": "Wrong1234"}
    codes = [client.post("/auth/login/", json=bad).status_code for _ in range(6)]

    assert codes[:5] == [401] * 5
    assert codes[5] == 429
    assert client.post("/auth/login/", json=bad).json() == {"detail": "Rate limit exceeded: 5 per 1 minute"}


def test_protected_route_requires_token(client):
    res = client.get("/auth/me/")

    assert res.status_code == 401
    assert res.headers["WWW-Authenticate"] == "Bearer"


@pytest.mark.parametrize(
    "token",
    [
        "garbage",
        jwt.encode({"sub": "1", "exp": datetime.now(timezone.utc) + timedelta(hours=1)}, "wrong-secret-" * 4, "HS256"),
        jwt.encode({"sub": "1", "exp": datetime.now(timezone.utc) - timedelta(seconds=1)}, settings.jwt_secret, "HS256"),
        jwt.encode({"sub": "1"}, settings.jwt_secret, "HS256"),  # no expiry
    ],
    ids=["malformed", "wrong-signature", "expired", "no-exp"],
)
def test_invalid_tokens_are_rejected(client, user, token):
    res = client.get("/auth/me/", headers={"Authorization": f"Bearer {token}"})

    assert res.status_code == 401


def test_token_for_deleted_user_is_rejected(client, db, user):
    headers = auth_headers(user)
    db.delete(user)
    db.commit()

    assert client.get("/auth/me/", headers=headers).status_code == 401
