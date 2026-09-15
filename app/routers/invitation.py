"""Public invitation endpoints.

Two consumers:
  * the email link `GET /invite?token=…` renders an HTML page that opens the
    mobile app via `adehun://open/invite?token=…` (Android intent fallback and
    store links otherwise);
  * the app calls `GET /invitations/{token}` to learn which agreement the
    token belongs to before routing to the invitation screen.

Both are unauthenticated by necessity, so they return the minimum: no email
addresses, no amounts, no participant profiles.
"""

from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse
from jinja2 import Environment, FileSystemLoader, select_autoescape
from pydantic import BaseModel

from app.config import settings
from app.core.response import APIResponse, NotFoundResponse, success_response
from app.database import SessionDep
from app.exceptions import InvitationNotFoundError
from app.models import Agreement, User
from app.rate_limiting import limiter
from app.service.invitation_service import find_invitation_by_token

router = APIRouter(tags=["Invitations"])

_templates = Environment(
    loader=FileSystemLoader(Path(__file__).resolve().parent.parent / "templates"),
    autoescape=select_autoescape(["html"]),
)

DEEP_LINK_SCHEME = "adehun"
DEEP_LINK_HOST = "open"


def deep_link_for(token: str) -> str:
    return f"{DEEP_LINK_SCHEME}://{DEEP_LINK_HOST}/invite?token={token}"


def android_intent_for(token: str) -> str:
    return (
        f"intent://{DEEP_LINK_HOST}/invite?token={token}"
        f"#Intent;scheme={DEEP_LINK_SCHEME};"
        f"package={settings.android_package_name};end"
    )


def _mask_email(email: str) -> str:
    local, _, domain = email.partition("@")
    if not domain:
        return "***"
    visible = local[:1]
    return f"{visible}***@{domain}"


def _is_live(status: str | None, expires_at: datetime) -> bool:
    if (status or "pending") != "pending":
        return False
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    return expires_at > datetime.now(timezone.utc)


class InvitationLookupResponse(BaseModel):
    agreement_id: str
    agreement_title: str
    inviter_name: str
    role: str
    status: str
    expires_at: datetime
    email_hint: str


@router.get(
    "/invitations/{token}",
    response_model=APIResponse[InvitationLookupResponse],
    responses={404: {"model": NotFoundResponse}},
)
@limiter.limit("20/minute")
async def lookup_invitation(request: Request, token: str, session: SessionDep):
    """Minimal, unauthenticated lookup so the app can route an invite link."""
    if len(token) > 128:
        raise InvitationNotFoundError()
    invitation = find_invitation_by_token(session, token)
    if invitation is None or not _is_live(invitation.status, invitation.expires_at):
        raise InvitationNotFoundError()

    agreement = session.get(Agreement, invitation.agreement_id)
    inviter = session.get(User, invitation.invited_by)
    return success_response(
        data=InvitationLookupResponse(
            agreement_id=invitation.agreement_id,
            agreement_title=agreement.title if agreement else "",
            inviter_name=inviter.name if inviter else "Someone",
            role=invitation.role,
            status=invitation.status or "pending",
            expires_at=invitation.expires_at,
            email_hint=_mask_email(invitation.email),
        )
    )


@router.get("/invite", include_in_schema=False, response_class=HTMLResponse)
@limiter.limit("30/minute")
async def invite_page(
    request: Request,
    session: SessionDep,
    token: str = Query(min_length=1, max_length=128),
):
    """Landing page for the emailed invitation link."""
    invitation = find_invitation_by_token(session, token)
    live = invitation is not None and _is_live(
        invitation.status, invitation.expires_at
    )
    agreement = (
        session.get(Agreement, invitation.agreement_id) if invitation else None
    )
    inviter = session.get(User, invitation.invited_by) if invitation else None

    html = _templates.get_template("invite.html").render(
        live=live,
        agreement_title=agreement.title if agreement else "",
        inviter_name=inviter.name if inviter else "Someone",
        role=invitation.role if invitation else "",
        deep_link=deep_link_for(token) if live else "",
        android_intent=android_intent_for(token) if live else "",
        ios_store_url=settings.ios_app_store_url,
        android_store_url=settings.android_play_store_url,
    )
    # The token sits in the URL: keep it out of caches and referrers.
    return HTMLResponse(
        html,
        status_code=200 if live else 404,
        headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"},
    )


@router.get("/.well-known/assetlinks.json", include_in_schema=False)
async def assetlinks():
    """Android App Links verification for https://<host>/invite links."""
    if not settings.android_cert_sha256:
        return JSONResponse([])
    return JSONResponse(
        [
            {
                "relation": ["delegate_permission/common.handle_all_urls"],
                "target": {
                    "namespace": "android_app",
                    "package_name": settings.android_package_name,
                    "sha256_cert_fingerprints": settings.android_cert_sha256,
                },
            }
        ]
    )
