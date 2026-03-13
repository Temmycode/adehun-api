from sqlmodel import Session, func, select

from app.models import Agreement, AgreementParticipant


class StatsRepository:
    def __init__(self, session: Session):
        self.session = session

    def get_user_stats(self, user_id: int) -> tuple[int, int, int]:
        """Get user stats by user id."""
        active_agreements_count = (
            func.count(Agreement.agreement_id)  # pyright: ignore[reportArgumentType]
            .filter(Agreement.status == "active")  # pyright: ignore[reportArgumentType]
            .label("active_agreements")
        )
        completed_agreements_count = (
            func.count(Agreement.agreement_id)  # pyright: ignore[reportArgumentType]
            .filter(Agreement.status == "completed")  # pyright: ignore[reportArgumentType]
            .label("completed_agreements")
        )
        total_agreements_count = func.count(Agreement.agreement_id).label(  # pyright: ignore[reportArgumentType]
            "total_agreements"
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

        return self.session.exec(stmt).scalar_one()
