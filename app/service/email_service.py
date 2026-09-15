import html

import resend

from ..config import settings
from ..logging import get_logger

resend.api_key = settings.resend_api_key
logger = get_logger(__name__)


def send_invitation_email(
    email: str,
    invitation_link: str,
    inviter_name: str = "Someone",
    agreement_title: str = "",
) -> None:
    """Send the escrow invitation. Every interpolated value is HTML-escaped."""
    if not settings.resend_api_key:
        logger.info("RESEND_API_KEY unset; skipping invitation email")
        return

    safe_link = html.escape(invitation_link, quote=True)
    safe_inviter = html.escape(inviter_name or "Someone")
    safe_title = html.escape(agreement_title or "an escrow agreement")

    body = (
        f"<p>{safe_inviter} has invited you to <strong>{safe_title}</strong> "
        f"on Adehun.</p>"
        f'<p><a href="{safe_link}">Open the invitation</a></p>'
        f"<p>If the button does not work, copy this link into your browser:<br>"
        f"{safe_link}</p>"
        f"<p>This invitation expires in 7 days.</p>"
    )

    try:
        resend.Emails.send(
            {
                "from": settings.resend_from_email,
                "to": email,
                "subject": f"{safe_inviter} invited you to an escrow on Adehun",
                "html": body,
            }
        )
    except Exception:
        logger.exception("failed to send invitation email")
