from app.logging import get_logger

from sqlmodel import Session, func, select

from app.models import Agreement, AgreementParticipant

logger = get_logger(__name__)


class StatsRepository:
    def __init__(self, session: Session):
        self.session = session

    def get_user_stats(self, user_id: str) -> tuple[int, int, int]:
        """Get user stats by user id."""
        active_agreements_count = (
            func.count(Agreement.id)  # pyright: ignore[reportArgumentType]
            .filter(Agreement.status == "active")  # pyright: ignore[reportArgumentType]
            .label("active")
        )
        completed_agreements_count = (
            func.count(Agreement.id)  # pyright: ignore[reportArgumentType]
            .filter(Agreement.status == "completed")  # pyright: ignore[reportArgumentType]
            .label("completed")
        )
        total_agreements_count = func.count(Agreement.id).label(  # pyright: ignore[reportArgumentType]
            "total"
        )

        stmt = (
            select(
                active_agreements_count,
                completed_agreements_count,
                total_agreements_count,
            )
            .join(AgreementParticipant)
            .where(AgreementParticipant.user_id == user_id)
        )

        result = self.session.exec(stmt).first() or (0, 0, 0)
        logger.debug(
            "fetched user stats",
            extra={
                "user_id": user_id,
                "active": result[0],
                "completed": result[1],
                "total": result[2],
            },
        )
        return result
