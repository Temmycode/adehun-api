"""Invite links: public lookup, HTML landing page, register-from-invite."""

import uuid
from datetime import datetime, timedelta, timezone

from sqlmodel import select

from app.models import Invitation


def _token_for(session, agreement_id: str) -> str:
    inv = session.exec(select(Invitation).where(Invitation.agreement_id == agreement_id)).first()
    assert inv is not None
    return inv.token


def test_lookup_returns_minimal_data(client, make_user, make_agreement, session):
    depositor = make_user(name="Grace Hopper")
    invitee = make_user(email="invitee@example.com")
    agreement = make_agreement(depositor, invitee, title="Ship the compiler")
    token = _token_for(session, agreement["id"])

    resp = client.get(f"/invitations/{token}")
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["agreement_id"] == agreement["id"]
    assert data["agreement_title"] == "Ship the compiler"
    assert data["inviter_name"] == "Grace Hopper"
    assert data["role"] == "beneficiary"
    assert data["email_hint"] == "i***@example.com"
    assert "invitee@example.com" not in resp.text
    assert "amount" not in data

    assert client.get("/invitations/not-a-token").status_code == 404


def test_invite_page_deep_links_and_escapes(client, make_user, make_agreement, session):
    depositor = make_user(name="<script>alert(1)</script>")
    invitee = make_user()
    agreement = make_agreement(depositor, invitee, title="Title <b>bold</b>")
    token = _token_for(session, agreement["id"])

    resp = client.get(f"/invite?token={token}")
    assert resp.status_code == 200
    assert resp.headers["cache-control"] == "no-store"
    assert resp.headers["referrer-policy"] == "no-referrer"
    assert f"adehun://open/invite?token={token}" in resp.text
    assert "intent://open/invite" in resp.text
    assert "<script>alert(1)</script>" not in resp.text
    assert "&lt;script&gt;" in resp.text
    assert "<b>bold</b>" not in resp.text

    resp = client.get("/invite?token=expired-or-unknown")
    assert resp.status_code == 404
    assert "no longer valid" in resp.text


def test_expired_invitation_is_rejected(client, make_user, make_agreement, session):
    depositor = make_user()
    invitee = make_user()
    agreement = make_agreement(depositor, invitee)
    inv = session.exec(select(Invitation).where(Invitation.agreement_id == agreement["id"])).first()
    inv.expires_at = datetime.now(timezone.utc) - timedelta(days=1)
    session.add(inv)
    session.commit()

    assert client.get(f"/invitations/{inv.token}").status_code == 404
    assert client.get(f"/invite?token={inv.token}").status_code == 404


def test_register_from_invite_without_redis(client, make_user, make_agreement, session, firebase):
    depositor = make_user()
    invitee_email = f"{uuid.uuid4().hex[:6]}@example.com"
    # The invitee has no account yet; make_agreement needs a User object only
    # for its email, so build a throwaway one that is not persisted.
    from app.models import User

    ghost = User(id="ghost", email=invitee_email, name="Ghost")
    agreement = make_agreement(depositor, ghost)
    token = _token_for(session, agreement["id"])

    uid = str(uuid.uuid4())
    id_token = firebase.register(uid, invitee_email, "New Person")
    resp = client.post(
        "/auth/register-from-invite",
        json={"id_token": id_token, "invitation_token": token},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["user"]["email"] == invitee_email
    assert data["is_signed_up"] is False

    # The new user was notified about the pending invitation with a routable id.
    resp = client.get("/notifications", headers={"Authorization": f"Bearer {data['access_token']}"})
    notes = resp.json()["data"]["notifications"]
    assert notes and notes[0]["type"] == "invitation_received"
    assert notes[0]["metadata"]["agreement_id"] == agreement["id"]

    # And can now see the agreement and accept it.
    headers = {"Authorization": f"Bearer {data['access_token']}", "Idempotency-Key": str(uuid.uuid4())}
    assert client.get(f"/agreements/{agreement['id']}", headers=headers).status_code == 200
    resp = client.post(f"/agreements/{agreement['id']}/accept", headers=headers)
    assert resp.status_code == 200, resp.text
    assert resp.json()["data"]["status"] == "active"

    # A consumed invitation no longer resolves.
    assert client.get(f"/invitations/{token}").status_code == 404
    resp = client.post("/auth/register-from-invite", json={"id_token": id_token, "invitation_token": token})
    assert resp.status_code == 404


def test_assetlinks_empty_without_fingerprint(client):
    resp = client.get("/.well-known/assetlinks.json")
    assert resp.status_code == 200
    assert resp.json() == []
