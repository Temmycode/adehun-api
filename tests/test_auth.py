import uuid

from app.service import token_service


def test_register_requires_auth(client):
    resp = client.post(
        "/auth/register", json={"phone_number": "+2348012345678", "name": "Ada"}
    )
    assert resp.status_code == 401


def test_register_updates_only_the_caller(client, make_user, auth_headers):
    me = make_user(name="Old", phone=None)
    other = make_user(name="Victim")

    resp = client.post(
        "/auth/register",
        json={"user_id": other.id, "phone_number": "+2348000000000", "name": "Hacked"},
        headers=auth_headers(me),
    )
    assert resp.status_code == 403

    resp = client.post(
        "/auth/register",
        json={"phone_number": "0801 234 5678", "name": "  Ada   Lovelace "},
        headers=auth_headers(me),
    )
    assert resp.status_code == 201, resp.text
    data = resp.json()["data"]
    assert data["id"] == me.id
    assert data["name"] == "Ada Lovelace"
    assert data["phone_number"] == "08012345678"

    resp = client.get("/users/current", headers=auth_headers(other))
    assert resp.json()["data"]["name"] == "Victim"


def test_register_rejects_bad_phone(client, make_user, auth_headers):
    me = make_user()
    resp = client.post(
        "/auth/register",
        json={"phone_number": "not-a-phone", "name": "Ada"},
        headers=auth_headers(me),
    )
    assert resp.status_code == 422


def test_login_issues_rotating_refresh_tokens(client, firebase, make_user):
    uid = str(uuid.uuid4())
    id_token = firebase.register(uid, "fresh@example.com", "Fresh")

    resp = client.post("/auth/login", json={"id_token": id_token})
    assert resp.status_code == 200, resp.text
    first = resp.json()["data"]
    assert first["is_signed_up"] is False
    assert first["user"]["email"] == "fresh@example.com"

    # Second login of an existing account.
    resp = client.post("/auth/login", json={"id_token": id_token})
    assert resp.json()["data"]["is_signed_up"] is True

    # Refresh rotates: the new pair works, the old refresh token is dead.
    resp = client.post("/auth/refresh", json={"refresh_token": first["refresh_token"]})
    assert resp.status_code == 200, resp.text
    second = resp.json()["data"]
    assert second["refresh_token"] != first["refresh_token"]

    resp = client.get(
        "/users/current", headers={"Authorization": f"Bearer {second['access_token']}"}
    )
    assert resp.status_code == 200

    # Reuse of the consumed token is treated as theft: the whole family dies.
    resp = client.post("/auth/refresh", json={"refresh_token": first["refresh_token"]})
    assert resp.status_code == 401
    resp = client.post("/auth/refresh", json={"refresh_token": second["refresh_token"]})
    assert resp.status_code == 401


def test_login_rejects_bad_firebase_token(client, firebase):
    resp = client.post("/auth/login", json={"id_token": "idtoken:nobody"})
    assert resp.status_code == 401


def test_logout_revokes_refresh_token(client, firebase):
    uid = str(uuid.uuid4())
    id_token = firebase.register(uid, "bye@example.com")
    tokens = client.post("/auth/login", json={"id_token": id_token}).json()["data"]

    resp = client.post("/auth/logout", json={"refresh_token": tokens["refresh_token"]})
    assert resp.status_code == 200
    resp = client.post("/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
    assert resp.status_code == 401


def test_inactive_user_is_rejected_everywhere(client, make_user, auth_headers):
    ghost = make_user(active=False)
    resp = client.get("/users/current", headers=auth_headers(ghost))
    assert resp.status_code == 401

    refresh = token_service.create_token(ghost.id, "refresh")
    resp = client.post("/auth/refresh", json={"refresh_token": refresh})
    assert resp.status_code == 401


def test_access_token_cannot_be_used_as_refresh(client, make_user):
    user = make_user()
    access = token_service.create_token(user.id, "access")
    resp = client.post("/auth/refresh", json={"refresh_token": access})
    assert resp.status_code == 401


def test_token_without_required_claims_is_rejected(client, make_user):
    import jwt

    user = make_user()
    legacy = jwt.encode(
        {"sub": user.id, "type": "access", "exp": 4102444800},
        token_service.SECRET_KEY,
        algorithm="HS256",
    )
    resp = client.get("/users/current", headers={"Authorization": f"Bearer {legacy}"})
    assert resp.status_code == 401


def test_dev_routes_and_docs_are_absent(client):
    assert client.post("/auth/dev-login", data={"username": "x", "password": "y"}).status_code == 404
    assert client.post("/auth/dev-promote-admin?email=x").status_code == 404
    assert client.get("/docs").status_code == 404
    assert client.get("/openapi.json").status_code == 404
