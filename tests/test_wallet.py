"""Withdrawals and bank accounts."""

import uuid
from decimal import Decimal

import pytest


def _add_account(client, user, headers, make_default=True):
    resp = client.post(
        "/bank-accounts",
        json={"account_number": "0123456789", "bank_code": "001", "make_default": make_default},
        headers=headers(user),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["data"]


def test_bank_account_lifecycle(client, make_user, auth_headers, paystack):
    user = make_user()
    other = make_user()

    resolved = client.post(
        "/bank-accounts/resolve",
        json={"account_number": "0123456789", "bank_code": "001"},
        headers=auth_headers(user),
    ).json()["data"]
    assert resolved["account_name"] == "ADA LOVELACE"
    assert resolved["bank_name"] == "Test Bank"

    account = _add_account(client, user, auth_headers)
    assert account["account_name"] == "ADA LOVELACE"  # from Paystack, never the client
    assert account["is_default"] is True

    # Duplicate is refused.
    resp = client.post(
        "/bank-accounts",
        json={"account_number": "0123456789", "bank_code": "001"},
        headers=auth_headers(user),
    )
    assert resp.status_code == 409

    # Other users cannot see, default or delete it.
    assert client.get("/bank-accounts", headers=auth_headers(other)).json()["data"] == []
    assert client.patch(f"/bank-accounts/{account['id']}/default", headers=auth_headers(other)).status_code == 404
    assert client.delete(f"/bank-accounts/{account['id']}", headers=auth_headers(other)).status_code == 404

    assert client.delete(f"/bank-accounts/{account['id']}", headers=auth_headers(user)).status_code == 200
    assert client.get("/bank-accounts", headers=auth_headers(user)).json()["data"] == []


def test_withdrawals_disabled_by_default(client, make_user, auth_headers, paystack, credit_wallet):
    user = make_user()
    credit_wallet(user, "1000.00")
    _add_account(client, user, auth_headers)
    resp = client.post(
        "/wallet/withdraw",
        json={"amount": "500.00"},
        headers={**auth_headers(user), "Idempotency-Key": str(uuid.uuid4())},
    )
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "WITHDRAWALS_DISABLED"


@pytest.fixture
def transfers_enabled(monkeypatch):
    monkeypatch.setattr("app.service.wallet_service.settings.paystack_transfers_enabled", True)


def test_withdrawal_debits_then_transfers(
    client, make_user, auth_headers, paystack, credit_wallet, transfers_enabled, post_webhook
):
    user = make_user()
    credit_wallet(user, "1000.00")
    account = _add_account(client, user, auth_headers)

    key = str(uuid.uuid4())
    resp = client.post(
        "/wallet/withdraw",
        json={"amount": "400.00", "bank_account_id": account["id"]},
        headers={**auth_headers(user), "Idempotency-Key": key},
    )
    assert resp.status_code == 202, resp.text
    wd = resp.json()["data"]
    assert wd["status"] == "pending"
    assert Decimal(wd["available_balance"]) == Decimal("600.00")
    assert [c[0] for c in paystack.calls if c[0] == "initiate_transfer"]

    # Replaying the same key does not debit twice.
    resp = client.post(
        "/wallet/withdraw",
        json={"amount": "400.00", "bank_account_id": account["id"]},
        headers={**auth_headers(user), "Idempotency-Key": key},
    )
    assert resp.status_code == 202
    assert Decimal(client.get("/wallet", headers=auth_headers(user)).json()["data"]["available_balance"]) == Decimal("600.00")

    # The ledger description never carries the full account number.
    txs = client.get("/transactions", headers=auth_headers(user)).json()["data"]["transactions"]
    wd_tx = next(t for t in txs if t["type"] == "withdrawal")
    assert "0123456789" not in wd_tx["description"]
    assert "6789" in wd_tx["description"]

    # transfer.success settles it after verification.
    resp = post_webhook({"event": "transfer.success", "data": {"id": 5, "reference": wd["reference"], "transfer_code": "TRF_test"}})
    assert resp.json()["status"] == "processed"
    status = client.get(f"/wallet/withdrawals/{wd['reference']}", headers=auth_headers(user)).json()["data"]
    assert status["status"] == "success"

    # Balances unchanged by settlement; money left at request time.
    assert Decimal(client.get("/wallet", headers=auth_headers(user)).json()["data"]["available_balance"]) == Decimal("600.00")


def test_failed_transfer_is_refunded_once(
    client, make_user, auth_headers, paystack, credit_wallet, transfers_enabled, post_webhook
):
    user = make_user()
    credit_wallet(user, "1000.00")
    _add_account(client, user, auth_headers)
    wd = client.post(
        "/wallet/withdraw",
        json={"amount": "250.00"},
        headers={**auth_headers(user), "Idempotency-Key": str(uuid.uuid4())},
    ).json()["data"]

    payload = {"event": "transfer.failed", "data": {"id": 9, "reference": wd["reference"], "reason": "Bank down"}}
    assert post_webhook(payload).json()["status"] == "reversed"
    assert post_webhook(payload).json()["status"] == "duplicate"
    payload["data"]["id"] = 10
    assert post_webhook(payload).json()["status"] == "already_processed"

    assert Decimal(client.get("/wallet", headers=auth_headers(user)).json()["data"]["available_balance"]) == Decimal("1000.00")


def test_provider_rejection_reverses_immediately(
    client, make_user, auth_headers, paystack, credit_wallet, transfers_enabled
):
    from app.service.paystack_client import PaystackValidationError

    user = make_user()
    credit_wallet(user, "1000.00")
    _add_account(client, user, auth_headers)
    paystack.transfer_error = PaystackValidationError("Invalid recipient")
    resp = client.post(
        "/wallet/withdraw",
        json={"amount": "250.00"},
        headers={**auth_headers(user), "Idempotency-Key": str(uuid.uuid4())},
    )
    assert resp.status_code >= 400
    assert Decimal(client.get("/wallet", headers=auth_headers(user)).json()["data"]["available_balance"]) == Decimal("1000.00")


def test_withdrawal_bounds_and_funds(client, make_user, auth_headers, paystack, credit_wallet, transfers_enabled):
    user = make_user()
    credit_wallet(user, "50.00")
    _add_account(client, user, auth_headers)
    headers = {**auth_headers(user), "Idempotency-Key": str(uuid.uuid4())}
    assert client.post("/wallet/withdraw", json={"amount": "10.00"}, headers=headers).status_code == 400
    headers["Idempotency-Key"] = str(uuid.uuid4())
    assert client.post("/wallet/withdraw", json={"amount": "500.00"}, headers=headers).status_code == 409
    # Other users' withdrawals are invisible.
    other = make_user()
    assert client.get("/wallet/withdrawals/WD-nope", headers=auth_headers(other)).status_code == 404
