from enum import StrEnum


class ParticipantRole(StrEnum):
    DEPOSITOR = "depositor"
    BENEFICIARY = "beneficiary"


class InvitationStatus(StrEnum):
    INVITED = "invited"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
