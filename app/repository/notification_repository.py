from typing import Any

from redis import Redis
from sqlmodel import Session, func, select

from app.logging import get_logger
from app.models import Notification
from app.redis import RedisClient

logger = get_logger(__name__)


class NotificationRepository(RedisClient):
    def __init__(self, session: Session, redis_client: Redis | None):
        super().__init__(redis_client)
        self.session = session

    def create(
        self,
        user_id: str,
        type: str,
        title: str,
        message: str,
        metadata: dict[str, Any] | None = None,
    ) -> Notification:
        notification = Notification(
            user_id=user_id,
            type=type,
            title=title,
            message=message,
            notification_metadata=metadata,
        )
        self.session.add(notification)
        self.session.commit()
        self.session.refresh(notification)
        return notification

    def get_by_user(
        self, user_id: str, skip: int = 0, limit: int = 20
    ) -> list[Notification]:
        results = self.session.exec(
            select(Notification)
            .where(Notification.user_id == user_id)
            .order_by(Notification.created_at.desc())  # pyright: ignore[reportAttributeAccessIssue]
            .offset(skip)
            .limit(limit)
        ).all()
        return list(results)

    def get_total_count(self, user_id: str) -> int:
        count = self.session.exec(
            select(func.count())
            .select_from(Notification)
            .where(Notification.user_id == user_id)
        ).one()
        return int(count)

    def get_unread_count(self, user_id: str) -> int:
        count = self.session.exec(
            select(func.count())
            .select_from(Notification)
            .where(
                Notification.user_id == user_id,
                Notification.is_read == False,  # noqa: E712
            )
        ).one()
        return int(count)

    def mark_as_read(self, notification_ids: list[str], user_id: str) -> int:
        if not notification_ids:
            return 0
        notifications = self.session.exec(
            select(Notification).where(
                Notification.user_id == user_id,
                Notification.id.in_(notification_ids),  # pyright: ignore[reportAttributeAccessIssue]
                Notification.is_read == False,  # noqa: E712
            )
        ).all()
        for n in notifications:
            n.is_read = True
            self.session.add(n)
        self.session.commit()
        return len(notifications)

    def mark_all_as_read(self, user_id: str) -> int:
        notifications = self.session.exec(
            select(Notification).where(
                Notification.user_id == user_id,
                Notification.is_read == False,  # noqa: E712
            )
        ).all()
        for n in notifications:
            n.is_read = True
            self.session.add(n)
        self.session.commit()
        return len(notifications)

    def get_by_id(
        self, notification_id: str, user_id: str
    ) -> Notification | None:
        return self.session.exec(
            select(Notification).where(
                Notification.id == notification_id,
                Notification.user_id == user_id,
            )
        ).first()

    def rollback(self) -> None:
        self.session.rollback()
