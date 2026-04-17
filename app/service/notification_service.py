from typing import Any

from app.common.enums import NotificationType
from app.logging import get_logger
from app.models import Notification
from app.repository.notification_repository import NotificationRepository
from app.schemas.notification_schema import (
    NotificationListResponse,
    NotificationResponse,
)

logger = get_logger(__name__)


class NotificationService:
    def __init__(self, notification_repo: NotificationRepository):
        self.notification_repo = notification_repo

    def create_notification(
        self,
        user_id: str,
        type: NotificationType,
        title: str,
        message: str,
        metadata: dict[str, Any] | None = None,
    ) -> Notification:
        notification = self.notification_repo.create(
            user_id=user_id,
            type=type.value,
            title=title,
            message=message,
            metadata=metadata,
        )
        logger.info(
            "notification created",
            extra={
                "notification_id": notification.id,
                "user_id": user_id,
                "type": type.value,
            },
        )
        return notification

    def get_user_notifications(
        self, user_id: str, skip: int = 0, limit: int = 20
    ) -> NotificationListResponse:
        notifications = self.notification_repo.get_by_user(user_id, skip, limit)
        unread_count = self.notification_repo.get_unread_count(user_id)
        total = self.notification_repo.get_total_count(user_id)
        return NotificationListResponse(
            notifications=[
                NotificationResponse.model_validate(n) for n in notifications
            ],
            unread_count=unread_count,
            total=total,
        )

    def get_unread_count(self, user_id: str) -> int:
        return self.notification_repo.get_unread_count(user_id)

    def mark_as_read(self, notification_ids: list[str], user_id: str) -> int:
        updated = self.notification_repo.mark_as_read(notification_ids, user_id)
        logger.info(
            "notifications marked as read",
            extra={"user_id": user_id, "updated_count": updated},
        )
        return updated

    def mark_all_as_read(self, user_id: str) -> int:
        updated = self.notification_repo.mark_all_as_read(user_id)
        logger.info(
            "all notifications marked as read",
            extra={"user_id": user_id, "updated_count": updated},
        )
        return updated
