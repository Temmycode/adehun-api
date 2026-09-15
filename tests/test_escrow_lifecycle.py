"""create -> accept -> fund -> approve -> release, plus every guard around it."""

import uuid
from decimal import Decimal

from sqlalchemy import text


def _balance(client, user, headers):
    resp = client.get("/wallet", headers=headers(user))
    assert resp.status_code == 200, resp.text
    return resp.json()["data"]


def _ledger_invariant_violations(session) -> int:
    """Every wallet balance must equal the sum of its completed ledger legs."""
    rows = session.execute(
        text(
            """
            SELECT w.id
            FROM wallet w
            LEFT JOIN (
                SELECT wallet_id,
                       SUM(available_delta) AS available,
                       SUM(escrow_delta) AS escrow
                FROM transaction
                GROUP BY wallet_id
            ) t ON t.wallet_id = w.id
            WHERE w.available_balance <> COALESCE(t.available, 0)
               OR w.escrow_balance <> COALESCE(t.escrow, 0)
            """
        )
    ).fetchall()
    return len(rows)


def test_full_happy_path(
    client, make_user, auth_headers, credit_wallet, make_agreement, accept_as, fund_as, session
):
    depositor = make_user(name="Dep")
    beneficiary = make_user(name="Ben")
    credit_wallet(depositor, "5000.00")

    agreement = make_agreement(depositor, beneficiary, amount="1200.50")
    aid = agreement["id"]
    assert agreement["status"] == "pending"
    assert agreement["is_funded"] is False
    assert agreement["condition_count"] == 1

    # Depositor cannot fund before the beneficiary accepts (no beneficiary yet).
    assert fund_as(depositor, aid).status_code == 404

    accepted = accept_as(beneficiary, aid)
    assert accepted["status"] == "active"
    assert accepted["current_user_accepted"] is True

    # Condition now points at the beneficiary's participant row.
    conds = client.get(f"/agreements/{aid}/conditions", headers=auth_headers(depositor)).json()["data"]
    assert conds[0]["required_from_participant"] is not None
    assert conds[0]["required_from_participant"]["user"]["id"] == beneficiary.id

    # Beneficiary cannot fund.
    assert fund_as(beneficiary, aid).status_code == 403

    key = str(uuid.uuid4())
    resp = fund_as(depositor, aid, key=key)
    assert resp.status_code == 200, resp.text
    move = resp.json()["data"]
    assert move["replayed"] is False
    assert Decimal(move["available_balance"]) == Decimal("3799.50")
    assert Decimal(move["escrow_balance"]) == Decimal("1200.50")

    # Same idempotency key replays; a new key is refused as already funded.
    replay = fund_as(depositor, aid, key=key)
    assert replay.status_code == 200
    assert replay.json()["data"]["reference"] == move["reference"]
    assert fund_as(depositor, aid).status_code == 400

    detail = client.get(f"/agreements/{aid}", headers=auth_headers(depositor)).json()["data"]
    assert detail["is_funded"] is True

    # Funded agreements cannot be cancelled unilaterally.
    assert client.post(f"/agreements/{aid}/cancel", headers=auth_headers(depositor)).status_code == 400

    cid = agreement["conditions"][0]["id"]
    # The beneficiary (who delivers the work) cannot approve their own condition.
    resp = client.post(f"/conditions/{cid}/approve", headers=auth_headers(beneficiary))
    assert resp.status_code == 403
    # The depositor approves; that was the last condition, so escrow releases.
    resp = client.post(f"/conditions/{cid}/approve", headers=auth_headers(depositor))
    assert resp.status_code == 200, resp.text
    assert resp.json()["data"]["status"] == "approved"

    detail = client.get(f"/agreements/{aid}", headers=auth_headers(beneficiary)).json()["data"]
    assert detail["status"] == "completed"
    assert detail["conditions_met_count"] == 1

    assert Decimal(_balance(client, beneficiary, auth_headers)["available_balance"]) == Decimal("1200.50")
    dep_wallet = _balance(client, depositor, auth_headers)
    assert Decimal(dep_wallet["available_balance"]) == Decimal("3799.50")
    assert Decimal(dep_wallet["escrow_balance"]) == Decimal("0.00")

    # The fallback release is a no-op replay, never a second payout.
    resp = client.post(
        f"/agreements/{aid}/release",
        headers={**auth_headers(beneficiary), "Idempotency-Key": str(uuid.uuid4())},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["data"]["replayed"] is True
    assert Decimal(_balance(client, beneficiary, auth_headers)["available_balance"]) == Decimal("1200.50")

    # Nothing can resurrect a completed agreement.
    assert (
        client.post(
            f"/agreements/{aid}/reject",
            headers={**auth_headers(beneficiary), "Idempotency-Key": str(uuid.uuid4())},
        ).status_code
        == 400
    )
    resp = client.post(
        f"/agreements/{aid}/accept",
        headers={**auth_headers(beneficiary), "Idempotency-Key": str(uuid.uuid4())},
    )
    assert resp.json()["data"]["status"] == "completed"  # idempotent early return

    assert _ledger_invariant_violations(session) == 0

    # Both parties see the movements in their ledgers.
    txs = client.get("/transactions", headers=auth_headers(depositor)).json()["data"]
    assert {t["type"] for t in txs["transactions"]} >= {"deposit", "escrow_lock", "escrow_release_out"}


def test_insufficient_funds_blocks_funding(
    client, make_user, credit_wallet, make_agreement, accept_as, fund_as
):
    depositor = make_user()
    beneficiary = make_user()
    credit_wallet(depositor, "100.00")
    agreement = make_agreement(depositor, beneficiary, amount="500.00")
    accept_as(beneficiary, agreement["id"])
    resp = fund_as(depositor, agreement["id"])
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "INSUFFICIENT_FUNDS"


def test_fund_requires_idempotency_key(client, make_user, auth_headers, make_agreement, accept_as):
    depositor = make_user()
    beneficiary = make_user()
    agreement = make_agreement(depositor, beneficiary)
    accept_as(beneficiary, agreement["id"])
    resp = client.post(f"/agreements/{agreement['id']}/fund", headers=auth_headers(depositor))
    assert resp.status_code == 422


def test_conditions_cannot_be_added_after_activation(
    client, make_user, auth_headers, make_agreement, accept_as
):
    depositor = make_user()
    beneficiary = make_user()
    agreement = make_agreement(depositor, beneficiary)
    aid = agreement["id"]

    resp = client.post(
        f"/agreements/{aid}/conditions",
        json={"title": "Extra", "description": "one more", "required_from_email": beneficiary.email},
        headers=auth_headers(depositor),
    )
    assert resp.status_code == 200, resp.text

    accept_as(beneficiary, aid)
    resp = client.post(
        f"/agreements/{aid}/conditions",
        json={"title": "Late", "description": "too late", "required_from_email": beneficiary.email},
        headers=auth_headers(depositor),
    )
    assert resp.status_code == 400


def test_conditions_only_decidable_while_active(client, make_user, auth_headers, make_agreement):
    depositor = make_user()
    beneficiary = make_user()
    agreement = make_agreement(depositor, beneficiary)
    cid = agreement["conditions"][0]["id"]
    resp = client.post(f"/conditions/{cid}/approve", headers=auth_headers(depositor))
    assert resp.status_code == 400  # still pending, nothing to release


def test_reject_then_approve_condition(
    client, make_user, auth_headers, credit_wallet, make_agreement, accept_as, fund_as
):
    depositor = make_user()
    beneficiary = make_user()
    credit_wallet(depositor, "1000.00")
    agreement = make_agreement(
        depositor,
        beneficiary,
        conditions=[
            {"title": "A", "description": "a", "required_from_email": beneficiary.email},
            {"title": "B", "description": "b", "required_from_email": beneficiary.email},
        ],
    )
    aid = agreement["id"]
    c1, c2 = (c["id"] for c in agreement["conditions"])
    accept_as(beneficiary, aid)
    assert fund_as(depositor, aid).status_code == 200

    resp = client.post(
        f"/conditions/{c1}/reject",
        json={"rejected_reason": "Not what we agreed"},
        headers=auth_headers(depositor),
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["status"] == "rejected"

    # Approving only one of two conditions does not release.
    assert client.post(f"/conditions/{c2}/approve", headers=auth_headers(depositor)).status_code == 200
    detail = client.get(f"/agreements/{aid}", headers=auth_headers(depositor)).json()["data"]
    assert detail["status"] == "active"
    assert detail["conditions_met_count"] == 1

    assert client.post(f"/conditions/{c1}/approve", headers=auth_headers(depositor)).status_code == 200
    detail = client.get(f"/agreements/{aid}", headers=auth_headers(depositor)).json()["data"]
    assert detail["status"] == "completed"


def test_decline_and_cancel_guards(client, make_user, auth_headers, make_agreement, accept_as):
    depositor = make_user()
    beneficiary = make_user()

    # Decline while pending cancels the agreement.
    agreement = make_agreement(depositor, beneficiary)
    resp = client.post(
        f"/agreements/{agreement['id']}/reject",
        headers={**auth_headers(beneficiary), "Idempotency-Key": str(uuid.uuid4())},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["data"]["status"] == "cancelled"
    # And it cannot be accepted afterwards.
    resp = client.post(
        f"/agreements/{agreement['id']}/accept",
        headers={**auth_headers(beneficiary), "Idempotency-Key": str(uuid.uuid4())},
    )
    assert resp.status_code == 400

    # Cancel a pending agreement as the creator.
    agreement = make_agreement(depositor, beneficiary)
    resp = client.post(f"/agreements/{agreement['id']}/cancel", headers=auth_headers(depositor))
    assert resp.status_code == 200
    assert resp.json()["data"]["status"] == "cancelled"
    # A cancelled agreement cannot be accepted (would resurrect it).
    resp = client.post(
        f"/agreements/{agreement['id']}/accept",
        headers={**auth_headers(beneficiary), "Idempotency-Key": str(uuid.uuid4())},
    )
    assert resp.status_code == 400


def test_admin_refund_and_guards(
    client, make_user, auth_headers, credit_wallet, make_agreement, accept_as, fund_as, session
):
    depositor = make_user()
    beneficiary = make_user()
    admin = make_user(is_admin=True)
    credit_wallet(depositor, "1000.00")
    agreement = make_agreement(depositor, beneficiary, amount="400.00")
    aid = agreement["id"]
    accept_as(beneficiary, aid)
    assert fund_as(depositor, aid).status_code == 200

    # Non-admins cannot refund.
    resp = client.post(
        f"/agreements/{aid}/refund",
        headers={**auth_headers(depositor), "Idempotency-Key": str(uuid.uuid4())},
    )
    assert resp.status_code == 403

    resp = client.post(
        f"/agreements/{aid}/refund",
        headers={**auth_headers(admin), "Idempotency-Key": str(uuid.uuid4())},
    )
    assert resp.status_code == 200, resp.text
    assert Decimal(resp.json()["data"]["available_balance"]) == Decimal("1000.00")

    detail = client.get(f"/agreements/{aid}", headers=auth_headers(depositor)).json()["data"]
    assert detail["status"] == "refunded"

    # A refunded agreement cannot be funded, accepted or released again.
    assert fund_as(depositor, aid).status_code == 400
    resp = client.post(
        f"/agreements/{aid}/release",
        headers={**auth_headers(depositor), "Idempotency-Key": str(uuid.uuid4())},
    )
    assert resp.status_code == 400
    assert _ledger_invariant_violations(session) == 0


def test_agreement_list_carries_counts_and_funded_flag(
    client, make_user, auth_headers, credit_wallet, make_agreement, accept_as, fund_as
):
    depositor = make_user()
    beneficiary = make_user()
    credit_wallet(depositor, "1000.00")
    agreement = make_agreement(depositor, beneficiary, amount="10.00")
    accept_as(beneficiary, agreement["id"])
    fund_as(depositor, agreement["id"])

    items = client.get("/agreements/", headers=auth_headers(beneficiary)).json()["data"]
    assert len(items) == 1
    assert items[0]["is_funded"] is True
    assert items[0]["condition_count"] == 1
    assert items[0]["current_user_accepted"] is True
