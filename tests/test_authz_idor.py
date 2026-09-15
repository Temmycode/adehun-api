"""Object-level authorization: user C must never see A and B's agreement."""

import uuid


def test_stranger_cannot_read_agreement_or_children(
    client, make_user, auth_headers, make_agreement, accept_as
):
    depositor = make_user(name="Dep")
    beneficiary = make_user(name="Ben")
    stranger = make_user(name="Eve")

    agreement = make_agreement(depositor, beneficiary)
    aid = agreement["id"]
    cid = agreement["conditions"][0]["id"]

    for path in (
        f"/agreements/{aid}",
        f"/agreements/{aid}/conditions",
        f"/conditions/{cid}",
        f"/conditions/{cid}/assets",
        f"/conditions/{cid}/assets/upload-signature",
        f"/agreement/{aid}/assets/",
        f"/agreements/{aid}/disputes",
    ):
        resp = client.get(path, headers=auth_headers(stranger))
        assert resp.status_code == 403, (path, resp.text)

    resp = client.post(
        f"/conditions/{cid}/assets",
        json={
            "files": [
                {
                    "url": "https://res.cloudinary.com/testcloud/x.png",
                    "type": "image",
                    "name": "x.png",
                    "size": 10,
                }
            ]
        },
        headers=auth_headers(stranger),
    )
    assert resp.status_code == 403

    resp = client.post(
        f"/agreements/{aid}/conditions",
        json={
            "title": "t",
            "description": "d",
            "required_from_email": beneficiary.email,
        },
        headers=auth_headers(stranger),
    )
    assert resp.status_code == 403

    # Both real parties can read.
    assert (
        client.get(f"/agreements/{aid}", headers=auth_headers(depositor)).status_code
        == 200
    )
    # The invitee can read before accepting (needed by the invitation screen).
    assert (
        client.get(f"/agreements/{aid}", headers=auth_headers(beneficiary)).status_code
        == 200
    )
    assert (
        client.get(
            f"/agreements/{aid}/conditions", headers=auth_headers(beneficiary)
        ).status_code
        == 200
    )


def test_unknown_agreement_is_404_not_403(client, make_user, auth_headers):
    user = make_user()
    resp = client.get(f"/agreements/{uuid.uuid4()}", headers=auth_headers(user))
    assert resp.status_code == 404


def test_stranger_cannot_fund_cancel_or_approve(
    client, make_user, auth_headers, make_agreement, accept_as, fund_as
):
    depositor = make_user()
    beneficiary = make_user()
    stranger = make_user()
    agreement = make_agreement(depositor, beneficiary)
    aid = agreement["id"]
    cid = agreement["conditions"][0]["id"]

    assert fund_as(stranger, aid).status_code in (403, 404)
    assert (
        client.post(
            f"/agreements/{aid}/cancel", headers=auth_headers(stranger)
        ).status_code
        == 403
    )
    assert (
        client.post(
            f"/conditions/{cid}/approve", headers=auth_headers(stranger)
        ).status_code
        == 403
    )


def test_user_cannot_patch_another_profile(client, make_user, auth_headers):
    me = make_user()
    other = make_user(name="Other")
    resp = client.patch(
        f"/users/{other.id}", json={"name": "Pwned"}, headers=auth_headers(me)
    )
    assert resp.status_code == 403
    assert (
        client.get("/users/current", headers=auth_headers(other)).json()["data"]["name"]
        == "Other"
    )


def test_notifications_are_user_scoped(client, make_user, auth_headers, session):
    from app.common.enums import NotificationType
    from app.repository.notification_repository import NotificationRepository

    a = make_user()
    b = make_user()
    repo = NotificationRepository(session, None)
    note = repo.create(
        a.id, NotificationType.GENERAL, "hi", "there", {"agreement_id": "x"}
    )

    resp = client.get("/notifications", headers=auth_headers(b))
    assert resp.status_code == 200
    assert resp.json()["data"]["total"] == 0

    resp = client.patch(
        "/notifications/read",
        json={"notification_ids": [note.id]},
        headers=auth_headers(b),
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["updated_count"] == 0

    resp = client.get("/notifications/unread-count", headers=auth_headers(a))
    assert resp.json()["data"]["unread_count"] == 1
