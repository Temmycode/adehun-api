"""Object-level authorization helpers.

Authentication proves *who* the caller is; these prove the caller may touch
*this* agreement. Every route that reads or mutates an agreement, its
conditions, or its assets goes through one of these.
"""

from sqlmodel import Session, select

from app.common.enums import ParticipantRole
from app.exceptions import AgreementNotFoundError, ForbiddenError
from app.models import Agreement, AgreementParticipant, Invitation


def _agreement_exists(session: Session, agreement_id: str) -> Agreement:
    agreement = session.get(Agreement, agreement_id)
    if agreement is None:
        raise AgreementNotFoundError()
    return agreement


def get_participant(
    session: Session, agreement_id: str, user_id: str
) -> AgreementParticipant | None:
    return session.exec(
        select(AgreementParticipant).where(
            AgreementParticipant.agreement_id == agreement_id,
            AgreementParticipant.user_id == user_id,
        )
    ).first()


def require_participant(
    session: Session, agreement_id: str, user_id: str
) -> AgreementParticipant:
    """Caller must hold a participant row on the agreement (any status)."""
    _agreement_exists(session, agreement_id)
    participant = get_participant(session, agreement_id, user_id)
    if participant is None:
        raise ForbiddenError("You are not a participant in this agreement")
    return participant


def require_role(
    session: Session, agreement_id: str, user_id: str, role: ParticipantRole
) -> AgreementParticipant:
    participant = require_participant(session, agreement_id, user_id)
    if participant.role != role:
        raise ForbiddenError(f"Only the {role.value} can perform this action")
    return participant


def has_pending_invitation(session: Session, agreement_id: str, email: str) -> bool:
    if not email:
        return False
    invitation = session.exec(
        select(Invitation).where(
            Invitation.agreement_id == agreement_id,
            Invitation.email == email,
        )
    ).first()
    return invitation is not None and (invitation.status or "pending") == "pending"


def require_read_access(
    session: Session, agreement_id: str, user_id: str, email: str
) -> None:
    """Participants may read; so may a pending invitee (matched by email).

    The invitee needs the agreement and its conditions on screen *before*
    deciding to accept, so the read rule is deliberately wider than the
    write rule. Writes always require `require_participant`.
    """
    _agreement_exists(session, agreement_id)
    if get_participant(session, agreement_id, user_id) is not None:
        return
    if has_pending_invitation(session, agreement_id, email):
        return
    raise ForbiddenError("You do not have access to this agreement")
