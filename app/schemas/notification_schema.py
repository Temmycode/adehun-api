from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class NotificationResponse(BaseModel):
    id: str
    type: str
    title: str
    message: str
    metadata: dict[str, Any] | None = Field(
        default=None, validation_alias="notification_metadata"
    )
    is_read: bool
    created_at: datetime

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


class NotificationListResponse(BaseModel):
    notifications: list[NotificationResponse]
    unread_count: int
    total: int


class MarkReadRequest(BaseModel):
    notification_ids: list[str]


class MarkReadResponse(BaseModel):
    updated_count: int


class UnreadCountResponse(BaseModel):
    unread_count: int
