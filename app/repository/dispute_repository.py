from redis import Redis
from sqlmodel import Session, col, func, or_, select

from app.common.enums import DisputeCategory, DisputeStatus
from app.logging import get_logger
from app.models import (
    Agreement,
    AgreementParticipant,
    Asset,
    AssetFile,
    Dispute,
)
from app.redis import RedisClient
from app.repository.agreement_repository import agreement_cache_keys
from app.schemas.asset_schema import AssetFile as AssetFileSchema

logger = get_logger(__name__)

_ACTIVE_STATUSES = (DisputeStatus.OPEN, DisputeStatus.UNDER_REVIEW)


class DisputeRepository(RedisClient):
    """Persistence for disputes, their evidence, and the agreement freeze.

    Deliberately does NOT cache. Disputes are low-volume and highly mutable,
    and the agreement cache is already this codebase's main source of stale
    reads. `RedisClient` is inherited only for `_cache_delete`, used to
    invalidate the agreement cache when a dispute freezes or unfreezes it.

    Note this repository writes `Agreement.status` directly rather than going
    through AgreementRepository. That is required for correctness on two
    counts: the dispute row and the freeze must land in ONE transaction (a
    dispute row with an unfrozen agreement would let escrow escape), and
    `AgreementRepository.get_by_id` returns a transient, session-detached
    instance on a cache hit, which cannot be mutated and saved.
    """

    def __init__(self, session: Session, redis_client: Redis | None):
        self.session = session
        super().__init__(redis_client)

    # ------------------------------------------------------------------ #
    #  Agreement context                                                  #
    # ------------------------------------------------------------------ #

    def get_agreement(self, agreement_id: str) -> Agreement | None:
        """Get an agreement by id, ATTACHED to the session.

        `session.get` rather than `AgreementRepository.get_by_id` — see the
        class docstring. We mutate `status` on the result, so it must be a
        live, session-managed instance.
        """
        return self.session.get(Agreement, agreement_id)

    def get_participants(self, agreement_id: str) -> list[AgreementParticipant]:
        """Every participant on an agreement."""
        return list(
            self.session.exec(
                select(AgreementParticipant).where(
                    AgreementParticipant.agreement_id == agreement_id
                )
            ).all()
        )

    def get_participant(
        self, agreement_id: str, user_id: str
    ) -> AgreementParticipant | None:
        """The caller's participant row, or None if they are not on the agreement."""
        return self.session.exec(
            select(AgreementParticipant).where(
                AgreementParticipant.agreement_id == agreement_id,
                AgreementParticipant.user_id == user_id,
            )
        ).first()

    # ------------------------------------------------------------------ #
    #  Reads — user-scoped                                                #
    #                                                                     #
    #  Every one of these puts user_id in the WHERE clause. Never fetch    #
    #  then compare in Python: a fetch-then-check is one careless edit     #
    #  away from leaking another user's dispute.                          #
    # ------------------------------------------------------------------ #

    def get_for_user(self, dispute_id: str, user_id: str) -> Dispute | None:
        """A dispute the given user is a party to, or None."""
        return self.session.exec(
            select(Dispute).where(
                Dispute.id == dispute_id,
                or_(
                    Dispute.raised_by_user_id == user_id,
                    Dispute.against_user_id == user_id,
                ),
            )
        ).first()

    def get_agreement_disputes_for_user(
        self, agreement_id: str, user_id: str
    ) -> list[Dispute]:
        """Disputes on an agreement the given user participates in."""
        return list(
            self.session.exec(
                select(Dispute)
                .join(
                    AgreementParticipant,
                    col(AgreementParticipant.agreement_id) == col(Dispute.agreement_id),
                )
                .where(
                    Dispute.agreement_id == agreement_id,
                    AgreementParticipant.user_id == user_id,
                )
                .order_by(col(Dispute.created_at).desc())
            ).all()
        )

    def list_for_user(self, user_id: str, skip: int, limit: int) -> list[Dispute]:
        """Disputes the user raised or is the respondent on, newest first."""
        return list(
            self.session.exec(
                select(Dispute)
                .where(
                    or_(
                        Dispute.raised_by_user_id == user_id,
                        Dispute.against_user_id == user_id,
                    )
                )
                .order_by(col(Dispute.created_at).desc())
                .offset(skip)
                .limit(limit)
            ).all()
        )

    def count_for_user(self, user_id: str) -> int:
        """Total disputes the user is a party to."""
        return (
            self.session.exec(
                select(func.count(col(Dispute.id))).where(
                    or_(
                        Dispute.raised_by_user_id == user_id,
                        Dispute.against_user_id == user_id,
                    )
                )
            ).first()
            or 0
        )

    # ------------------------------------------------------------------ #
    #  Reads — unscoped (admin only)                                      #
    #                                                                     #
    #  AdminUserDep on the route is the ONLY gate on these. Do not call    #
    #  them from a user-facing service method.                            #
    # ------------------------------------------------------------------ #

    def get_by_id(self, dispute_id: str) -> Dispute | None:
        """Any dispute, unscoped. Admin paths only."""
        return self.session.get(Dispute, dispute_id)

    def list_all(
        self,
        *,
        status: DisputeStatus | None,
        category: DisputeCategory | None,
        skip: int,
        limit: int,
    ) -> list[Dispute]:
        """The admin queue, newest first."""
        stmt = select(Dispute)
        if status is not None:
            stmt = stmt.where(Dispute.status == status)
        if category is not None:
            stmt = stmt.where(Dispute.category == category)
        stmt = stmt.order_by(col(Dispute.created_at).desc()).offset(skip).limit(limit)
        return list(self.session.exec(stmt).all())

    def count_all(
        self, *, status: DisputeStatus | None, category: DisputeCategory | None
    ) -> int:
        """Total matching the admin queue filters."""
        stmt = select(func.count(col(Dispute.id)))
        if status is not None:
            stmt = stmt.where(Dispute.status == status)
        if category is not None:
            stmt = stmt.where(Dispute.category == category)
        return self.session.exec(stmt).first() or 0

    # ------------------------------------------------------------------ #
    #  Shared reads                                                       #
    # ------------------------------------------------------------------ #

    def get_active_for_agreement(self, agreement_id: str) -> Dispute | None:
        """The live dispute on an agreement, if any.

        Mirrors the predicate of the `ux_dispute_one_active_per_agreement`
        partial unique index, so this and the database agree on what "active"
        means.
        """
        return self.session.exec(
            select(Dispute).where(
                Dispute.agreement_id == agreement_id,
                col(Dispute.status).in_(_ACTIVE_STATUSES),
            )
        ).first()

    def get_evidence(self, dispute_id: str) -> list[Asset]:
        """Evidence attached to a dispute. Callers must authorise first."""
        return list(
            self.session.exec(
                select(Asset).where(Asset.dispute_id == dispute_id)
            ).all()
        )

    # ------------------------------------------------------------------ #
    #  Writes                                                             #
    # ------------------------------------------------------------------ #

    def save(self, dispute: Dispute, *, commit: bool = True) -> Dispute:
        """Persist a dispute. `commit=False` to batch with the agreement freeze."""
        self.session.add(dispute)
        if commit:
            self.session.commit()
            self.session.refresh(dispute)
        else:
            self.session.flush()
        return dispute

    def add_evidence(
        self,
        dispute_id: str,
        participant_id: str,
        files: list[AssetFileSchema],
        *,
        commit: bool = True,
    ) -> list[Asset]:
        """Attach uploaded files to a dispute as evidence.

        Reuses AssetFile/Asset so evidence renders with the same client
        components as condition deliverables. `condition_id` stays NULL, which
        the `ck_asset_single_parent` constraint requires and which keeps
        evidence out of the deliverable feeds (they INNER JOIN Condition).
        """
        assets: list[Asset] = []
        for file in files:
            asset_file = AssetFile(
                url=file.url, type=file.type, name=file.name, size=file.size
            )
            self.session.add(asset_file)
            self.session.flush()

            asset = Asset(
                dispute_id=dispute_id,
                condition_id=None,
                file_id=asset_file.id,
                uploaded_by=participant_id,
            )
            self.session.add(asset)
            assets.append(asset)

        if commit:
            self.session.commit()
            for asset in assets:
                self.session.refresh(asset)
        else:
            self.session.flush()
        return assets

    def set_agreement_status(
        self, agreement: Agreement, status: str, *, commit: bool = True
    ) -> Agreement:
        """Freeze or unfreeze an agreement.

        `agreement` must be session-attached — pass the result of
        `get_agreement`, never one from AgreementRepository's cache.
        """
        agreement.status = status
        self.session.add(agreement)
        if commit:
            self.session.commit()
            self.session.refresh(agreement)
        else:
            self.session.flush()
        return agreement

    def commit(self) -> None:
        """Commit the current transaction."""
        self.session.commit()

    def rollback(self) -> None:
        """Roll back the current transaction."""
        self.session.rollback()

    def refresh(self, dispute: Dispute) -> None:
        """Refresh a dispute instance from the DB."""
        self.session.refresh(dispute)

    # ------------------------------------------------------------------ #
    #  Cache                                                              #
    # ------------------------------------------------------------------ #

    def invalidate_agreement_cache(self, agreement_id: str, user_ids: list[str]) -> None:
        """Drop the agreement's cached copies after a freeze or unfreeze.

        Mandatory, and always AFTER the commit. Skip it and
        `AgreementRepository.get_by_id` keeps serving the pre-dispute status
        for five minutes — long enough for escrow to be released on an
        agreement that is supposedly frozen.
        """
        self._cache_delete(*agreement_cache_keys(agreement_id, user_ids))
