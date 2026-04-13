import resend

from ..config import settings

resend.api_key = settings.resend_api_key


def send_invitation_email(email: str, invitation_link: str):
    """
    Sends an invitation email using Resend.
    """

    resend.Emails.send(
        {
            "from": "tolutech2004@gsmail.com",
            "to": email,
            "subject": "You've been invited to join Adehun",
            "html": f"<p>You've been invited to join Adehun. Click <a href='{invitation_link}'>here</a> to accept.</p>",
        }
    )
