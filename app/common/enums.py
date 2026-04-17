from enum import StrEnum


class ParticipantRole(StrEnum):
    DEPOSITOR = "depositor"
    BENEFICIARY = "beneficiary"


class InvitationStatus(StrEnum):
    INVITED = "invited"
    ACCEPTED = "accepted"
    REJECTED = "rejected"


class NotificationType(StrEnum):
    INVITATION_RECEIVED = "invitation_received"
    AGREEMENT_ACCEPTED = "agreement_accepted"
    AGREEMENT_DECLINED = "agreement_declined"
    CONDITION_ADDED = "condition_added"
    CONDITION_UPDATED = "condition_updated"
    AGREEMENT_COMPLETED = "agreement_completed"
    GENERAL = "general"
