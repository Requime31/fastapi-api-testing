# tests/test_users.py

def test_register(client):
    response = client.post("/users/register", json={
        "email": "test@example.com",
        "password": "123456"
    })
    assert response.status_code == 201
    assert response.json()["message"] == "User created"


def test_register_duplicate(client):
    client.post("/users/register", json={
        "email": "test@example.com",
        "password": "123456"
    })
    response = client.post("/users/register", json={
        "email": "test@example.com",
        "password": "123456"
    })
    assert response.status_code == 400
    assert response.json()["detail"] == "User already exists"


def test_register_invalid_email(client):
    response = client.post("/users/register", json={
        "email": "not-an-email",
        "password": "123456"
    })
    assert response.status_code == 422


import pytest


@pytest.mark.parametrize("password", ["abc12", "", "      "])
def test_register_rejects_weak_password(client, password):
    """FAT-8: shorter than 6 characters, empty and whitespace-only passwords are rejected."""
    response = client.post("/users/register", json={
        "email": "weak@example.com",
        "password": password
    })
    assert response.status_code == 422
    assert response.json()["detail"][0]["loc"] == ["body", "password"]


def test_register_password_min_length_boundary(client):
    """FAT-8: exactly 6 characters is the lower boundary and is accepted."""
    response = client.post("/users/register", json={
        "email": "boundary@example.com",
        "password": "abc123"
    })
    assert response.status_code == 201


def test_register_duplicate_email_different_case(client):
    """FAT-9: the same address in another case is a duplicate."""
    client.post("/users/register", json={"email": "Case@Example.com", "password": "123456"})
    response = client.post("/users/register", json={"email": "CASE@EXAMPLE.COM", "password": "123456"})
    assert response.status_code == 400
    assert response.json()["detail"] == "User already exists"


def test_login_email_case_insensitive(client):
    """FAT-9: login works with the email in any case."""
    client.post("/users/register", json={"email": "Case@Example.com", "password": "123456"})
    for email in ("case@example.com", "CASE@EXAMPLE.COM", "Case@Example.com"):
        response = client.post("/users/login", json={"email": email, "password": "123456"})
        assert response.status_code == 200, email


@pytest.mark.parametrize("payload", [
    {"phone": None},
    {},
    {"phone": "+31612345678"},
])
def test_register_phone_optional(client, payload):
    """FAT-15: an explicit null for the optional phone is the same as omitting it."""
    response = client.post("/users/register", json={
        "email": "phone@example.com",
        "password": "123456",
        **payload
    })
    assert response.status_code == 201


def test_login(client):
    client.post("/users/register", json={
        "email": "test@example.com",
        "password": "123456"
    })
    response = client.post("/users/login", json={
        "email": "test@example.com",
        "password": "123456"
    })
    assert response.status_code == 200
    assert "access_token" in response.json()
    assert response.cookies.get("refresh_token") is not None


def test_login_wrong_password(client):
    client.post("/users/register", json={
        "email": "test@example.com",
        "password": "123456"
    })
    response = client.post("/users/login", json={
        "email": "test@example.com",
        "password": "wrongpassword"
    })
    assert response.status_code == 401


def test_login_nonexistent_user(client):
    response = client.post("/users/login", json={
        "email": "nobody@example.com",
        "password": "123456"
    })
    assert response.status_code == 404


# ───── Refresh Token ─────

def test_refresh(client, auth_data):
    client.cookies.set("refresh_token", auth_data["refresh_token"])
    response = client.post("/users/refresh")
    assert response.status_code == 200
    assert "access_token" in response.json()
    assert response.cookies.get("refresh_token") is not None


def test_refresh_rotates_token(client, auth_data):
    old_refresh = auth_data["refresh_token"]
    client.cookies.set("refresh_token", old_refresh)
    response = client.post("/users/refresh")
    new_refresh = response.cookies.get("refresh_token")
    assert new_refresh != old_refresh


def test_refresh_old_token_invalid(client, auth_data):
    old_refresh = auth_data["refresh_token"]
    client.cookies.set("refresh_token", old_refresh)
    client.post("/users/refresh")

    client.cookies.set("refresh_token", old_refresh)
    response = client.post("/users/refresh")
    assert response.status_code == 401


def test_refresh_no_cookie(client):
    response = client.post("/users/refresh")
    assert response.status_code == 401


# ───── Logout ─────

def test_logout(client, auth_data):
    client.cookies.set("refresh_token", auth_data["refresh_token"])
    response = client.post("/users/logout")
    assert response.status_code == 200
    assert response.json()["message"] == "Logged out"


def test_logout_log_has_user_id(client, auth_data):
    """FAT-19: the logout log record carries the user_id of the session owner."""
    from app import models
    from .conftest import TestingSessionLocal

    client.cookies.set("refresh_token", auth_data["refresh_token"])
    assert client.post("/users/logout").status_code == 200

    db = TestingSessionLocal()
    try:
        user = db.query(models.User).filter(models.User.email == auth_data["email"]).one()
        record = db.query(models.Log).filter(models.Log.path == "/users/logout").order_by(models.Log.id.desc()).first()
        assert record is not None
        assert record.user_id == user.id
    finally:
        db.close()


def test_logout_invalidates_token(client, auth_data):
    client.cookies.set("refresh_token", auth_data["refresh_token"])
    client.post("/users/logout")

    client.cookies.set("refresh_token", auth_data["refresh_token"])
    response = client.post("/users/refresh")
    assert response.status_code == 401


# ───── Logout All ─────

def test_logout_all(client, auth_data):
    response = client.post("/users/logout-all", headers=auth_data["headers"])
    assert response.status_code == 200
    assert response.json()["message"] == "Logged out from all devices"


def test_logout_all_invalidates_all_tokens(client, auth_data):
    client.post("/users/logout-all", headers=auth_data["headers"])

    client.cookies.set("refresh_token", auth_data["refresh_token"])
    response = client.post("/users/refresh")
    assert response.status_code == 401

def test_access_protected_route_without_token(client):
    """FAT-13: a missing Authorization header is 401 with WWW-Authenticate, not 403."""
    response = client.get("/items/")
    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"


def test_logout_all_without_token(client):
    """FAT-13: /users/logout-all documents 401 for missing credentials."""
    response = client.post("/users/logout-all")
    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"


def test_non_bearer_scheme_is_401(client):
    """FAT-13: a non-Bearer scheme is treated as missing credentials."""
    response = client.get("/items/", headers={"Authorization": "Basic dXNlcjpwYXNz"})
    assert response.status_code == 401


def test_invalid_token_has_www_authenticate(client):
    response = client.get("/items/", headers={"Authorization": "Bearer invalid"})
    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"

