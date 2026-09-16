"""Profile read/update and avatar upload signature."""


def test_update_own_profile(client, make_user, auth_headers):
    me = make_user(name="Before", phone=None)

    resp = client.patch(
        f"/users/{me.id}",
        json={"name": "After  Name", "phone_number": "+234 801 234 5678"},
        headers=auth_headers(me),
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["name"] == "After Name"
    assert data["phone_number"] == "+2348012345678"
    assert data["is_admin"] is False

    current = client.get("/users/current", headers=auth_headers(me)).json()["data"]
    assert current["name"] == "After Name"

    # No-op patch still returns the user.
    resp = client.patch(f"/users/{me.id}", json={}, headers=auth_headers(me))
    assert resp.status_code == 200
    assert resp.json()["data"]["name"] == "After Name"


def test_avatar_must_be_our_cloudinary(client, make_user, auth_headers):
    me = make_user()
    resp = client.patch(
        f"/users/{me.id}",
        json={"profile_picture_url": "https://evil.example.com/me.png"},
        headers=auth_headers(me),
    )
    assert resp.status_code == 422

    resp = client.patch(
        f"/users/{me.id}",
        json={"profile_picture_url": "https://res.cloudinary.com/testcloud/adehun/profiles/x/me.png"},
        headers=auth_headers(me),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["data"]["profile_picture_url"].endswith("/me.png")


def test_profile_upload_signature_is_scoped(client, make_user, auth_headers):
    me = make_user()
    resp = client.get("/users/upload-signature", headers=auth_headers(me))
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["folder"] == f"adehun/profiles/{me.id}"
    assert data["signature"]
    assert data["api_key"] == "cloud-key"


def test_invalid_profile_values(client, make_user, auth_headers):
    me = make_user()
    for body in ({"name": "x"}, {"phone_number": "abc"}, {"name": "a" * 81}):
        resp = client.patch(f"/users/{me.id}", json=body, headers=auth_headers(me))
        assert resp.status_code == 422, body
