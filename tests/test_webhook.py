"""Paystack webhook: signature, verify-before-credit, replay, transfer events."""

import uuid
from decimal import Decimal


def _start_fund(client, user, headers, paystack, amount="2500.00"):
    resp = client.post(
        "/wallet/fund",
        json={"amount": amount, "channel": "card"},
        headers={**headers(user), "Idempotency-Key": str(uuid.uuid4())},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["data"]


def _charge_payload(reference, amount_kobo, event_id=None, currency="NGN"):
    return {
        "event": "charge.success",
        "data": {
            "id": event_id or 12345,
            "reference": reference,
            "amount": amount_kobo,
            "currency": currency,
            "channel": "card",
            "status": "success",
        },
    }


def test_bad_signature_is_rejected(client, make_user, post_webhook):
    resp = post_webhook(_charge_payload("nope", 100), secret="wrong-secret")
    assert resp.status_code == 401


def test_charge_is_credited_only_after_verification(
    client, make_user, auth_headers, paystack, post_webhook
):
    user = make_user()
    fund = _start_fund(client, user, auth_headers, paystack)
    ref = fund["reference"]
    assert fund["access_code"] == "ac_test"

    # Verify says it never settled: no credit.
    paystack.verify_result = {"status": "failed", "currency": "NGN", "amount": 250000}
    resp = post_webhook(_charge_payload(ref, 250000, event_id=1))
    assert resp.status_code == 200
    assert resp.json()["status"] == "not_verified"
    assert (
        Decimal(
            client.get("/wallet", headers=auth_headers(user)).json()["data"][
                "available_balance"
            ]
        )
        == 0
    )

    # Verify agrees: credit the VERIFIED amount, not the body's amount.
    paystack.verify_result = {"status": "success", "currency": "NGN", "amount": 250000}
    resp = post_webhook(_charge_payload(ref, 999999999, event_id=2))
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "processed"
    wallet = client.get("/wallet", headers=auth_headers(user)).json()["data"]
    assert Decimal(wallet["available_balance"]) == Decimal("2500.00")

    # Same event redelivered: duplicate, no second credit.
    resp = post_webhook(_charge_payload(ref, 250000, event_id=2))
    assert resp.json()["status"] == "duplicate"
    # A different event id for an already-settled reference: no second credit.
    resp = post_webhook(_charge_payload(ref, 250000, event_id=3))
    assert resp.json()["status"] == "already_processed"
    wallet = client.get("/wallet", headers=auth_headers(user)).json()["data"]
    assert Decimal(wallet["available_balance"]) == Decimal("2500.00")


def test_foreign_currency_is_ignored(
    client, make_user, auth_headers, paystack, post_webhook
):
    user = make_user()
    ref = _start_fund(client, user, auth_headers, paystack)["reference"]
    paystack.verify_result = {"status": "success", "currency": "USD", "amount": 250000}
    resp = post_webhook(_charge_payload(ref, 250000))
    assert resp.json()["status"] == "unsupported_currency"
    assert (
        Decimal(
            client.get("/wallet", headers=auth_headers(user)).json()["data"][
                "available_balance"
            ]
        )
        == 0
    )


def test_verify_outage_asks_paystack_to_retry(
    client, make_user, auth_headers, paystack, post_webhook, paystack_error
):
    user = make_user()
    ref = _start_fund(client, user, auth_headers, paystack)["reference"]
    paystack.verify_error = paystack_error("down")
    resp = post_webhook(_charge_payload(ref, 250000, event_id=7))
    assert resp.status_code == 500

    # Once Paystack is back, the redelivery succeeds.
    paystack.verify_error = None
    paystack.verify_result = {"status": "success", "currency": "NGN", "amount": 250000}
    resp = post_webhook(_charge_payload(ref, 250000, event_id=7))
    assert resp.status_code == 200
    assert resp.json()["status"] == "processed"


def test_unknown_reference_is_acknowledged_without_credit(post_webhook, paystack):
    resp = post_webhook(_charge_payload("does-not-exist", 100))
    assert resp.status_code == 200
    assert resp.json()["status"] == "unknown_reference"


def test_fund_records_intent_before_calling_paystack(
    client, make_user, auth_headers, paystack, paystack_error, session
):
    from app.models import PaystackTransaction
    from sqlmodel import select

    user = make_user()
    paystack.initialize_error = paystack_error("gateway exploded")
    resp = client.post(
        "/wallet/fund",
        json={"amount": "100.00", "channel": "card"},
        headers={**auth_headers(user), "Idempotency-Key": str(uuid.uuid4())},
    )
    assert resp.status_code >= 400
    row = session.exec(
        select(PaystackTransaction).where(PaystackTransaction.user_id == user.id)
    ).first()
    assert row is not None
    assert str(getattr(row.status, "value", row.status)).lower() == "failed"


def test_failed_webhook_is_not_retried_forever(
    client, make_user, auth_headers, paystack, post_webhook, paystack_error
):
    user = make_user()
    ref = _start_fund(client, user, auth_headers, paystack)["reference"]
    paystack.verify_error = paystack_error("down")
    for _ in range(5):
        assert (
            post_webhook(_charge_payload(ref, 250000, event_id=42)).status_code == 500
        )
    # Sixth delivery: refused as a duplicate rather than driven again.
    resp = post_webhook(_charge_payload(ref, 250000, event_id=42))
    assert resp.status_code == 200
    assert resp.json()["status"] == "duplicate"
