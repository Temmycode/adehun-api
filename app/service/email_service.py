import resend

from ..config import settings
from ..logging import get_logger

resend.api_key = settings.resend_api_key
logger = get_logger(__name__)


def send_invitation_email(email: str, invitation_link: str):
    """
    Sends an invitation email using Resend.
    """

    try:
        resend.Emails.send(
            {
                "from": "tolutech2004@gsmail.com",
                "to": email,
                "subject": "You've been invited to join Adehun",
                "html": f"<p>You've been invited to join Adehun. Click <a href='{invitation_link}'>here</a> to accept.</p>",
            }
        )
    except Exception as exc:
        logger.exception(
            "failed to send invitation email",
            extra={"email": email, "invitation_link": invitation_link},
            exc_info=exc,
        )
