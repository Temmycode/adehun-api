"""Whole-agreement disputes, resolved by a platform admin.

RECORD-ONLY BY DESIGN. Resolving a dispute writes an outcome, closes the row,
and unfreezes the agreement. It never moves money. This module must not import
WalletService, WalletRepository, Transaction or LedgerEntryType — if you find
yourself reaching for one, the requirement changed and this docstring needs to
change with it.
"""

from datetime import datetime, timezone

from sqlalchemy.exc import IntegrityError

from app.common.enums import (
    AgreementStatus,
    DisputeCategory,
    DisputeResolutionOutcome,
    DisputeStatus,
    InvitationStatus,
)
from app.exceptions import (
    AgreementNotFoundError,
    BadRequestError,
    DisputeAlreadyExistsError,
    DisputeCreationError,
    DisputeNotFoundError,
    DisputeNotOpenError,
    ForbiddenError,
    ParticipantNotFoundError,
)
from app.logging import get_logger
from app.models import Dispute
from app.repository.dispute_repository import DisputeRepository
from app.schemas.asset_schema import AssetResponse
from app.schemas.dispute_schema import (
    DisputeCreateRequest,
    DisputeEvidenceCreateRequest,
    DisputeListResponse,
    DisputeResolveRequest,
    DisputeResponse,
)
from app.schemas.image_upload_schema import SignedUploadResponse
from app.schemas.user_schema import UserResponse
from app.service.image_upload_service import create_upload_signature

logger = get_logger(__name__)

_OPEN_STATUSES = {DisputeStatus.OPEN, DisputeStatus.UNDER_REVIEW}


class DisputeService:
    def __init__(self, dispute_repo: DisputeRepository):
        self.dispute_repo = dispute_repo

    # ------------------------------------------------------------------ #
    #  Internals                                                          #
    # ------------------------------------------------------------------ #

    def _require_participant(self, agreement_id: str, user_id: str):
        """The caller's accepted participant row, or raise.

        Only an accepted participant can raise a dispute — an invitee who never
        joined has nothing to contest.
        """
        participant = self.dispute_repo.get_participant(agreement_id, user_id)
        if participant is None:
            raise ForbiddenError("You are not a participant on this agreement")
        if participant.status != InvitationStatus.ACCEPTED:
            raise ForbiddenError(
                "You must have accepted this agreement to raise a dispute"
            )
        return participant

    def _participant_user_ids(self, agreement_id: str) -> list[str]:
        return [p.user_id for p in self.dispute_repo.get_participants(agreement_id)]

    def _to_response(
        self, dispute: Dispute, *, with_evidence: bool = False
    ) -> DisputeResponse:
        agreement = dispute.agreement
        evidence: list[AssetResponse] = []
        if with_evidence:
            evidence = [
                AssetResponse.model_validate(asset)
                for asset in self.dispute_repo.get_evidence(dispute.id)
            ]

        return DisputeResponse(
            id=dispute.id,
            agreement_id=dispute.agreement_id,
            agreement_title=agreement.title if agreement else "",
            agreement_amount=agreement.amount if agreement else 0,
            category=DisputeCategory(dispute.category),
            description=dispute.description,
            status=DisputeStatus(dispute.status),
            raised_by=(
                UserResponse.model_validate(dispute.raised_by)
                if dispute.raised_by
                else None
            ),
            against_user=(
                UserResponse.model_validate(dispute.against_user)
                if dispute.against_user
                else None
            ),
            resolution_outcome=(
                DisputeResolutionOutcome(dispute.resolution_outcome)
                if dispute.resolution_outcome
                else None
            ),
            resolution_notes=dispute.resolution_notes,
            resolved_by=(
                UserResponse.model_validate(dispute.resolved_by)
                if dispute.resolved_by
                else None
            ),
            resolved_at=dispute.resolved_at,
            created_at=dispute.created_at,
            updated_at=dispute.updated_at,
            evidence=evidence,
        )

    # ------------------------------------------------------------------ #
    #  User-facing                                                        #
    # ------------------------------------------------------------------ #

    def create_upload_signature(
        self, agreement_id: str, user_id: str
    ) -> SignedUploadResponse:
        """Signed Cloudinary params for evidence upload.

        Same direct-to-Cloudinary flow as condition assets, into the
        `adehun/disputes` folder instead of `adehun/assets`.
        """
        self._require_participant(agreement_id, user_id)
        return create_upload_signature("disputes")

    def raise_dispute(
        self, agreement_id: str, user_id: str, data: DisputeCreateRequest
    ) -> DisputeResponse:
        """Open a dispute and freeze the agreement.

        The dispute row, its evidence, and the freeze all land in ONE
        transaction. Splitting them would allow a dispute to exist against an
        agreement that is still releasable.
        """
        agreement = self.dispute_repo.get_agreement(agreement_id)
        if agreement is None:
            raise AgreementNotFoundError()

        participant = self._require_participant(agreement_id, user_id)

        # The duplicate check comes FIRST. Raising a dispute freezes the
        # agreement to `disputed`, so a second attempt would otherwise trip the
        # status check below and return a confusing 400 ("an agreement that is
        # disputed cannot be disputed") instead of the accurate 409.
        if self.dispute_repo.get_active_for_agreement(agreement_id) is not None:
            raise DisputeAlreadyExistsError()

        if agreement.status != AgreementStatus.ACTIVE:
            raise BadRequestError(
                f"An agreement that is {agreement.status} cannot be disputed"
            )

        # The respondent is always derived server-side, never client-supplied.
        other = next(
            (
                p
                for p in self.dispute_repo.get_participants(agreement_id)
                if p.user_id != user_id
            ),
            None,
        )
        if other is None:
            raise ParticipantNotFoundError(
                "Agreement does not yet have a second participant"
            )

        status_before = agreement.status

        try:
            dispute = Dispute(
                agreement_id=agreement_id,
                raised_by_user_id=user_id,
                against_user_id=other.user_id,
                category=data.category,
                description=data.description,
                status=DisputeStatus.OPEN,
                agreement_status_before=status_before,
            )
            self.dispute_repo.save(dispute, commit=False)

            if data.files:
                self.dispute_repo.add_evidence(
                    dispute.id, participant.id, data.files, commit=False
                )

            self.dispute_repo.set_agreement_status(
                agreement, AgreementStatus.DISPUTED, commit=False
            )
            self.dispute_repo.commit()
            self.dispute_repo.refresh(dispute)
        except IntegrityError as err:
            # Lost the race against the partial unique index.
            self.dispute_repo.rollback()
            logger.info(
                "concurrent dispute rejected by unique index",
                extra={"agreement_id": agreement_id, "user_id": user_id},
            )
            raise DisputeAlreadyExistsError() from err
        except Exception as err:
            self.dispute_repo.rollback()
            logger.exception(
                "failed to raise dispute",
                extra={"agreement_id": agreement_id, "user_id": user_id},
            )
            raise DisputeCreationError() from err

        # After the commit, never before — see the repo method's docstring.
        self.dispute_repo.invalidate_agreement_cache(
            agreement_id, [user_id, other.user_id]
        )

        logger.warning(
            "dispute raised",
            extra={
                "dispute_id": dispute.id,
                "agreement_id": agreement_id,
                "category": str(data.category),
                "raised_by": user_id,
                "against": other.user_id,
            },
        )
        return self._to_response(dispute, with_evidence=True)

    def add_evidence(
        self, dispute_id: str, user_id: str, data: DisputeEvidenceCreateRequest
    ) -> list[AssetResponse]:
        """Attach further evidence to a live dispute. Either party may."""
        dispute = self.dispute_repo.get_for_user(dispute_id, user_id)
        if dispute is None:
            raise DisputeNotFoundError()
        if dispute.status not in _OPEN_STATUSES:
            raise DisputeNotOpenError()

        participant = self._require_participant(dispute.agreement_id, user_id)

        try:
            assets = self.dispute_repo.add_evidence(
                dispute.id, participant.id, data.files
            )
        except Exception as err:
            self.dispute_repo.rollback()
            logger.exception(
                "failed to add dispute evidence",
                extra={"dispute_id": dispute_id, "user_id": user_id},
            )
            raise DisputeCreationError("Failed to add evidence") from err

        return [AssetResponse.model_validate(asset) for asset in assets]

    def get_dispute(self, dispute_id: str, user_id: str) -> DisputeResponse:
        dispute = self.dispute_repo.get_for_user(dispute_id, user_id)
        if dispute is None:
            # 404 rather than 403 so we do not disclose that the dispute exists.
            raise DisputeNotFoundError()
        return self._to_response(dispute, with_evidence=True)

    def get_agreement_disputes(
        self, agreement_id: str, user_id: str
    ) -> list[DisputeResponse]:
        self._require_participant(agreement_id, user_id)
        return [
            self._to_response(d)
            for d in self.dispute_repo.get_agreement_disputes_for_user(
                agreement_id, user_id
            )
        ]

    def get_user_disputes(
        self, user_id: str, skip: int = 0, limit: int = 20
    ) -> DisputeListResponse:
        disputes = self.dispute_repo.list_for_user(user_id, skip, limit)
        return DisputeListResponse(
            disputes=[self._to_response(d) for d in disputes],
            total=self.dispute_repo.count_for_user(user_id),
        )

    # ------------------------------------------------------------------ #
    #  Admin                                                              #
    #                                                                     #
    #  These are unscoped. AdminUserDep on the route is the only gate.     #
    # ------------------------------------------------------------------ #

    def admin_list_disputes(
        self,
        *,
        status: DisputeStatus | None = None,
        category: DisputeCategory | None = None,
        skip: int = 0,
        limit: int = 20,
    ) -> DisputeListResponse:
        disputes = self.dispute_repo.list_all(
            status=status, category=category, skip=skip, limit=limit
        )
        return DisputeListResponse(
            disputes=[self._to_response(d) for d in disputes],
            total=self.dispute_repo.count_all(status=status, category=category),
        )

    def admin_get_dispute(self, dispute_id: str) -> DisputeResponse:
        dispute = self.dispute_repo.get_by_id(dispute_id)
        if dispute is None:
            raise DisputeNotFoundError()
        return self._to_response(dispute, with_evidence=True)

    def admin_mark_under_review(
        self, dispute_id: str, admin_user_id: str
    ) -> DisputeResponse:
        """Claim a dispute, so two admins do not resolve the same one."""
        dispute = self.dispute_repo.get_by_id(dispute_id)
        if dispute is None:
            raise DisputeNotFoundError()
        if dispute.status != DisputeStatus.OPEN:
            raise DisputeNotOpenError(
                f"This dispute is already {dispute.status}"
            )

        dispute.status = DisputeStatus.UNDER_REVIEW
        dispute.updated_at = datetime.now(timezone.utc)
        self.dispute_repo.save(dispute)

        logger.info(
            "dispute marked under review",
            extra={"dispute_id": dispute_id, "admin_user_id": admin_user_id},
        )
        return self._to_response(dispute, with_evidence=True)

    def admin_resolve_dispute(
        self, dispute_id: str, admin_user_id: str, data: DisputeResolveRequest
    ) -> DisputeResponse:
        """Record a binding outcome and unfreeze the agreement.

        RECORD-ONLY: no wallet or ledger call happens here for any outcome.
        `favour_beneficiary` restores the agreement to `active` so the normal
        release flow can run — setting it to `completed` here would
        permanently block the very release the outcome intends.
        """
        dispute = self.dispute_repo.get_by_id(dispute_id)
        if dispute is None:
            raise DisputeNotFoundError()
        if dispute.status not in _OPEN_STATUSES:
            raise DisputeNotOpenError()

        dispute.status = DisputeStatus.RESOLVED
        dispute.resolution_outcome = data.outcome
        dispute.resolution_notes = data.resolution_notes
        dispute.resolved_by_user_id = admin_user_id
        dispute.resolved_at = datetime.now(timezone.utc)
        dispute.updated_at = datetime.now(timezone.utc)

        agreement = self.dispute_repo.get_agreement(dispute.agreement_id)
        # Only unfreeze what this dispute froze — if something else legitimately
        # moved the status on, leave it alone.
        if agreement is not None and agreement.status == AgreementStatus.DISPUTED:
            self.dispute_repo.set_agreement_status(
                agreement,
                dispute.agreement_status_before or AgreementStatus.ACTIVE,
                commit=False,
            )

        try:
            self.dispute_repo.save(dispute, commit=False)
            self.dispute_repo.commit()
            self.dispute_repo.refresh(dispute)
        except Exception as err:
            self.dispute_repo.rollback()
            logger.exception(
                "failed to resolve dispute",
                extra={"dispute_id": dispute_id, "admin_user_id": admin_user_id},
            )
            raise DisputeCreationError("Failed to resolve dispute") from err

        self.dispute_repo.invalidate_agreement_cache(
            dispute.agreement_id,
            self._participant_user_ids(dispute.agreement_id),
        )

        logger.warning(
            "dispute resolved",
            extra={
                "dispute_id": dispute_id,
                "agreement_id": dispute.agreement_id,
                "outcome": str(data.outcome),
                "admin_user_id": admin_user_id,
            },
        )
        return self._to_response(dispute, with_evidence=True)
