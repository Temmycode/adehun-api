"""Input validation at the edges: pagination, uploads, money, roles."""

import pytest


@pytest.mark.parametrize(
    "path",
    ["/notifications", "/disputes", "/transactions"],
)
@pytest.mark.parametrize("query", ["limit=0", "limit=101", "skip=-1"])
def test_pagination_bounds(client, make_user, auth_headers, path, query):
    user = make_user()
    resp = client.get(f"{path}?{query}", headers=auth_headers(user))
    assert resp.status_code == 422, (path, query, resp.text)


def test_admin_pagination_bounds(client, make_user, auth_headers):
    admin = make_user(is_admin=True)
    assert client.get("/admin/disputes?limit=500", headers=auth_headers(admin)).status_code == 422


@pytest.mark.parametrize(
    "file",
    [
        {"url": "http://res.cloudinary.com/testcloud/a.png", "type": "image", "name": "a", "size": 1},
        {"url": "https://evil.example.com/a.png", "type": "image", "name": "a", "size": 1},
        {"url": "https://res.cloudinary.com/othercloud/a.png", "type": "image", "name": "a", "size": 1},
        {"url": "https://res.cloudinary.com/testcloud/a.png", "type": "image", "name": "a", "size": 0},
        {"url": "https://res.cloudinary.com/testcloud/a.png", "type": "unknown", "name": "a", "size": 1},
        {"url": "javascript:alert(1)", "type": "image", "name": "a", "size": 1},
    ],
)
def test_asset_file_validation(client, make_user, auth_headers, make_agreement, accept_as, file):
    depositor = make_user()
    beneficiary = make_user()
    agreement = make_agreement(depositor, beneficiary)
    accept_as(beneficiary, agreement["id"])
    cid = agreement["conditions"][0]["id"]
    resp = client.post(
        f"/conditions/{cid}/assets", json={"files": [file]}, headers=auth_headers(beneficiary)
    )
    assert resp.status_code == 422, resp.text


def test_asset_upload_accepts_our_cloud_and_limits_count(
    client, make_user, auth_headers, make_agreement, accept_as
):
    depositor = make_user()
    beneficiary = make_user()
    agreement = make_agreement(depositor, beneficiary)
    accept_as(beneficiary, agreement["id"])
    cid = agreement["conditions"][0]["id"]
    good = {"url": "https://res.cloudinary.com/testcloud/adehun/assets/x/a.png", "type": "image", "name": "a.png", "size": 1234}

    resp = client.post(f"/conditions/{cid}/assets", json={"files": [good] * 11}, headers=auth_headers(beneficiary))
    assert resp.status_code == 422

    resp = client.post(f"/conditions/{cid}/assets", json={"files": [good]}, headers=auth_headers(beneficiary))
    assert resp.status_code == 200, resp.text
    assert resp.json()["data"][0]["file"]["url"] == good["url"]

    sig = client.get(f"/conditions/{cid}/assets/upload-signature", headers=auth_headers(beneficiary)).json()["data"]
    assert sig["folder"] == f"adehun/assets/{cid}"
    assert sig["cloud_name"] == "testcloud"
    assert "expires_at" in sig


@pytest.mark.parametrize(
    "overrides",
    [
        {"role": "owner"},
        {"amount": "0"},
        {"amount": "-5"},
        {"amount": "10.005"},
        {"amount": "999999999999"},
        {"other_participant_email_or_phone": "+2348012345678"},
        {"title": ""},
        {"conditions": [{"title": "x", "description": "y", "required_from_email": "z"}]},
    ],
)
def test_agreement_create_validation(client, make_user, auth_headers, overrides):
    user = make_user()
    body = {
        "other_participant_email_or_phone": "friend@example.com",
        "role": "depositor",
        "title": "T",
        "description": "D",
        "amount": "100.00",
        "conditions": [],
    }
    body.update(overrides)
    resp = client.post("/agreements/", json=body, headers=auth_headers(user))
    assert resp.status_code == 422, resp.text


def test_cannot_invite_yourself(client, make_user, auth_headers):
    user = make_user()
    resp = client.post(
        "/agreements/",
        json={
            "other_participant_email_or_phone": user.email.upper(),
            "role": "beneficiary",
            "title": "T",
            "description": "D",
            "amount": "100.00",
            "conditions": [],
        },
        headers=auth_headers(user),
    )
    assert resp.status_code == 400


def test_wallet_fund_bounds(client, make_user, auth_headers, paystack):
    user = make_user()
    for amount in ("0", "10.001", "99999999999"):
        resp = client.post(
            "/wallet/fund", json={"amount": amount}, headers=auth_headers(user)
        )
        assert resp.status_code == 422, amount


def test_split_dispute_outcome_is_rejected(client, make_user, auth_headers):
    admin = make_user(is_admin=True)
    resp = client.post(
        "/admin/disputes/nope/resolve",
        json={"outcome": "split", "resolution_notes": "half and half please"},
        headers=auth_headers(admin),
    )
    assert resp.status_code == 422


def test_bank_list_currency_is_restricted(client, make_user, auth_headers, paystack):
    user = make_user()
    assert client.get("/bank-accounts/banks?currency=USD", headers=auth_headers(user)).status_code == 422
    resp = client.get("/bank-accounts/banks", headers=auth_headers(user))
    assert resp.status_code == 200
    assert resp.json()["data"][0]["code"] == "001"
