"""Disputes freeze the agreement; resolution settles the money."""

import uuid
from decimal import Decimal


def _funded_agreement(make_user, credit_wallet, make_agreement, accept_as, fund_as, amount="300.00"):
    depositor = make_user()
    beneficiary = make_user()
    credit_wallet(depositor, "1000.00")
    agreement = make_agreement(depositor, beneficiary, amount=amount)
    accept_as(beneficiary, agreement["id"])
    assert fund_as(depositor, agreement["id"]).status_code == 200
    return depositor, beneficiary, agreement


def _raise(client, user, headers, aid):
    resp = client.post(
        f"/agreements/{aid}/disputes",
        json={"category": "quality_issues", "description": "The delivered work is nothing like what we agreed on."},
        headers=headers(user),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["data"]


def _balance(client, user, headers):
    return Decimal(client.get("/wallet", headers=headers(user)).json()["data"]["available_balance"])


def test_dispute_freezes_agreement(client, make_user, auth_headers, credit_wallet, make_agreement, accept_as, fund_as):
    depositor, beneficiary, agreement = _funded_agreement(make_user, credit_wallet, make_agreement, accept_as, fund_as)
    aid = agreement["id"]
    cid = agreement["conditions"][0]["id"]
    stranger = make_user()

    resp = client.post(
        f"/agreements/{aid}/disputes",
        json={"category": "other", "description": "I am not even part of this agreement."},
        headers=auth_headers(stranger),
    )
    assert resp.status_code in (403, 404)

    dispute = _raise(client, beneficiary, auth_headers, aid)
    assert dispute["status"] == "open"
    assert client.get(f"/agreements/{aid}", headers=auth_headers(depositor)).json()["data"]["status"] == "disputed"

    # Only one live dispute, and nothing moves while it is open.
    resp = client.post(
        f"/agreements/{aid}/disputes",
        json={"category": "other", "description": "Second dispute on the same agreement."},
        headers=auth_headers(depositor),
    )
    assert resp.status_code == 409
    assert client.post(f"/conditions/{cid}/approve", headers=auth_headers(depositor)).status_code == 400
    assert client.post(f"/agreements/{aid}/cancel", headers=auth_headers(depositor)).status_code == 400

    # Non-admins cannot touch the admin queue.
    assert client.get("/admin/disputes", headers=auth_headers(depositor)).status_code == 403
    # But each party can see their own dispute; a stranger cannot.
    assert client.get(f"/disputes/{dispute['id']}", headers=auth_headers(depositor)).status_code == 200
    assert client.get(f"/disputes/{dispute['id']}", headers=auth_headers(stranger)).status_code in (403, 404)


def test_resolve_in_favour_of_beneficiary_releases(client, make_user, auth_headers, credit_wallet, make_agreement, accept_as, fund_as):
    depositor, beneficiary, agreement = _funded_agreement(make_user, credit_wallet, make_agreement, accept_as, fund_as)
    admin = make_user(is_admin=True)
    dispute = _raise(client, beneficiary, auth_headers, agreement["id"])

    assert client.patch(f"/admin/disputes/{dispute['id']}/review", headers=auth_headers(admin)).status_code == 200
    resp = client.post(
        f"/admin/disputes/{dispute['id']}/resolve",
        json={"outcome": "favour_beneficiary", "resolution_notes": "Evidence shows the work was delivered."},
        headers=auth_headers(admin),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["data"]["status"] == "resolved"
    assert "message" not in resp.json()

    assert _balance(client, beneficiary, auth_headers) == Decimal("300.00")
    assert _balance(client, depositor, auth_headers) == Decimal("700.00")
    assert client.get(f"/agreements/{agreement['id']}", headers=auth_headers(depositor)).json()["data"]["status"] == "completed"

    # Resolving twice is refused.
    resp = client.post(
        f"/admin/disputes/{dispute['id']}/resolve",
        json={"outcome": "favour_depositor", "resolution_notes": "Changed my mind about it."},
        headers=auth_headers(admin),
    )
    assert resp.status_code == 409


def test_resolve_in_favour_of_depositor_refunds(client, make_user, auth_headers, credit_wallet, make_agreement, accept_as, fund_as):
    depositor, beneficiary, agreement = _funded_agreement(make_user, credit_wallet, make_agreement, accept_as, fund_as)
    admin = make_user(is_admin=True)
    dispute = _raise(client, depositor, auth_headers, agreement["id"])

    resp = client.post(
        f"/admin/disputes/{dispute['id']}/resolve",
        json={"outcome": "favour_depositor", "resolution_notes": "Nothing was ever delivered."},
        headers=auth_headers(admin),
    )
    assert resp.status_code == 200, resp.text
    assert _balance(client, depositor, auth_headers) == Decimal("1000.00")
    assert _balance(client, beneficiary, auth_headers) == Decimal("0.00")
    assert client.get(f"/agreements/{agreement['id']}", headers=auth_headers(depositor)).json()["data"]["status"] == "refunded"


def test_dismissed_moves_nothing(client, make_user, auth_headers, credit_wallet, make_agreement, accept_as, fund_as):
    depositor, beneficiary, agreement = _funded_agreement(make_user, credit_wallet, make_agreement, accept_as, fund_as)
    admin = make_user(is_admin=True)
    dispute = _raise(client, depositor, auth_headers, agreement["id"])

    resp = client.post(
        f"/admin/disputes/{dispute['id']}/resolve",
        json={"outcome": "dismissed", "resolution_notes": "Both parties agreed to continue."},
        headers=auth_headers(admin),
    )
    assert resp.status_code == 200
    assert _balance(client, depositor, auth_headers) == Decimal("700.00")
    assert client.get(f"/agreements/{agreement['id']}", headers=auth_headers(depositor)).json()["data"]["status"] == "active"

    # The deal resumes: depositor can now approve and release.
    cid = agreement["conditions"][0]["id"]
    assert client.post(f"/conditions/{cid}/approve", headers=auth_headers(depositor)).status_code == 200
    assert _balance(client, beneficiary, auth_headers) == Decimal("300.00")


def test_evidence_urls_are_validated(client, make_user, auth_headers, credit_wallet, make_agreement, accept_as, fund_as):
    depositor, beneficiary, agreement = _funded_agreement(make_user, credit_wallet, make_agreement, accept_as, fund_as)
    dispute = _raise(client, depositor, auth_headers, agreement["id"])
    bad = {"url": "https://evil.example/x.png", "type": "image", "name": "x", "size": 1}
    resp = client.post(f"/disputes/{dispute['id']}/evidence", json={"files": [bad]}, headers=auth_headers(depositor))
    assert resp.status_code == 422
    good = {"url": "https://res.cloudinary.com/testcloud/adehun/disputes/x/a.png", "type": "image", "name": "a.png", "size": 10}
    resp = client.post(f"/disputes/{dispute['id']}/evidence", json={"files": [good]}, headers=auth_headers(depositor))
    assert resp.status_code == 200, resp.text
    sig = client.get(f"/agreements/{agreement['id']}/disputes/upload-signature", headers=auth_headers(depositor)).json()["data"]
    assert sig["folder"].startswith("adehun/disputes/")
