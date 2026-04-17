# Feature: In-App Notification System

## Stack
- **Language:** Python
- **Framework:** FastAPI
- **ORM:** SQLAlchemy (follow existing project patterns)
- **Architecture:** Services / Controllers (Routers) / Repos — match existing project structure exactly

---

## Overview

Build a self-contained notification feature that other features (agreements, invitations,
conditions, etc.) can trigger from their controllers/routes. Notifications are created
synchronously (just a DB write), while any external delivery (push, email) happens via
FastAPI `BackgroundTasks`.

**Orchestration rule:** Services must never call other feature services directly.
All cross-feature orchestration happens at the controller/route level. The
`NotificationService` is called from the agreement/invitation/condition routes —
not from inside `AgreementService` or any other service.

---

## Data Model

Create the `Notification` model following the existing SQLAlchemy model patterns in the project.

### Fields

| Field        | Type      | Notes                                                        |
|--------------|-----------|--------------------------------------------------------------|
| `id`         | UUID      | Primary key, generated on creation                           |
| `user_id`    | UUID      | Foreign key → users table. The recipient of the notification |
| `type`       | Enum/str  | See notification types below                                 |
| `title`      | str       | Short heading e.g. "New Escrow Invitation"                   |
| `message`    | str       | Human-readable body e.g. "John invited you to an agreement"  |
| `metadata`   | JSON/dict | Flexible payload — store IDs needed for deep linking         |
| `is_read`    | bool      | Defaults to `False`                                          |
| `created_at` | datetime  | UTC, set on creation                                         |

### Notification Types

Define these as an Enum (follow existing enum patterns in the project):

```
INVITATION_RECEIVED       - User was invited to an escrow agreement
AGREEMENT_ACCEPTED        - A participant accepted the agreement
AGREEMENT_DECLINED        - A participant declined the agreement
CONDITION_ADDED           - A new condition was added to an agreement
CONDITION_UPDATED         - A condition was updated
AGREEMENT_COMPLETED       - All parties have accepted, agreement is complete
GENERAL                   - Catch-all for anything that doesn't fit above
```

Add more types as the product grows — the Enum is the single source of truth.

### Metadata Examples

The `metadata` field is a flexible JSON column. Store whatever the client needs
for deep linking into the relevant screen:

```python
# Invitation notification
{"agreement_id": "abc-123", "invited_by_name": "John Doe"}

# Condition added
{"agreement_id": "abc-123", "condition_id": "def-456"}

# Agreement completed
{"agreement_id": "abc-123"}
```

---

## File Structure

Follow the exact folder/file structure already used in the project for other features.
The structure should mirror how agreements, invitations, or conditions are organised.
Typical structure:

```
app/
  features/
    notifications/
      router.py         # Route definitions
      service.py        # Business logic
      repo.py           # Database queries
      schemas.py        # Pydantic request/response schemas
      models.py         # SQLAlchemy model (or add to existing models file)
      dependencies.py   # NotificationServiceDep (follow existing dep patterns)
```

---

## Repository (`repo.py`)

Implement the following methods. Follow the existing repo patterns in the project
(session handling, query style, etc.):

```python
def create(self, user_id, type, title, message, metadata) -> Notification
def get_by_user(self, user_id, skip, limit) -> list[Notification]
def get_unread_count(self, user_id) -> int
def mark_as_read(self, notification_ids: list[str], user_id: str) -> int  # returns count updated
def mark_all_as_read(self, user_id: str) -> int
def get_by_id(self, notification_id: str, user_id: str) -> Notification | None
```

**Security note:** Every query that reads or mutates notifications must filter by
`user_id`. A user must never be able to read or mark another user's notifications.

---

## Service (`service.py`)

The service wraps the repo and contains any business logic. Keep it simple:

```python
def create_notification(
    self,
    user_id: str,
    type: NotificationType,
    title: str,
    message: str,
    metadata: dict | None = None,
) -> Notification

def get_user_notifications(
    self,
    user_id: str,
    skip: int = 0,
    limit: int = 20,
) -> list[Notification]

def get_unread_count(self, user_id: str) -> int

def mark_as_read(
    self,
    notification_ids: list[str],
    user_id: str,
) -> int

def mark_all_as_read(self, user_id: str) -> int
```

---

## Schemas (`schemas.py`)

### Response schemas

```python
class NotificationResponse(BaseModel):
    id: str
    type: str
    title: str
    message: str
    metadata: dict | None
    is_read: bool
    created_at: datetime

class NotificationListResponse(BaseModel):
    notifications: list[NotificationResponse]
    unread_count: int
    total: int

class MarkReadRequest(BaseModel):
    notification_ids: list[str]

class MarkReadResponse(BaseModel):
    updated_count: int
```

Wrap all endpoint responses in the existing `APIResponse[T]` envelope.

---

## Routes (`router.py`)

### Endpoints to implement

```
GET    /notifications            Get paginated notifications for current user
GET    /notifications/unread-count   Get unread count only (for badge display)
PATCH  /notifications/read       Mark a list of notification IDs as read
PATCH  /notifications/read-all   Mark all notifications as read
```

### Route details

**GET /notifications**
- Query params: `skip: int = 0`, `limit: int = 20`
- Returns: `APIResponse[NotificationListResponse]`
- Auth: required

**GET /notifications/unread-count**
- Returns: `APIResponse[dict]` with `{"unread_count": int}`
- Auth: required
- Used by the client to show the badge count on the notification bell

**PATCH /notifications/read**
- Body: `MarkReadRequest` (list of notification IDs)
- Returns: `APIResponse[MarkReadResponse]`
- Auth: required
- Only marks notifications that belong to the current user — silently ignores IDs
  that don't belong to them

**PATCH /notifications/read-all**
- No body
- Returns: `APIResponse[MarkReadResponse]`
- Auth: required

### Swagger documentation

Follow the existing pattern in the project for `responses={}` and `response_model`.
At minimum document `401: UnauthorizedResponse` on every route since all routes
require authentication.

---

## Triggering Notifications From Other Features

Notifications are created from **controllers/routes**, not from inside other services.

### Pattern

In any route that should trigger a notification, inject `NotificationServiceDep`
alongside the feature's own service dep, then call `notification_service.create_notification`
**after** the main operation succeeds:

```python
@router.post("/", status_code=201, ...)
async def create_agreement(
    request: Request,
    current_user: ActiveUserDep,
    agreement_data: AgreementCreate,
    agreement_service: AgreementServiceDep,
    notification_service: NotificationServiceDep,   # inject here
    background_tasks: BackgroundTasks,
):
    # 1. Main operation
    agreement = agreement_service.create_agreement(
        current_user.id,
        agreement_data,
        background_tasks,
    )

    # 2. Notify each invited participant (synchronous — just a DB write)
    for participant in agreement.participants:
        if participant.user_id != current_user.id:
            notification_service.create_notification(
                user_id=participant.user_id,
                type=NotificationType.INVITATION_RECEIVED,
                title="New Escrow Invitation",
                message=f"{current_user.full_name} invited you to an escrow agreement",
                metadata={"agreement_id": str(agreement.id)},
            )

    return success_response(data=agreement, status_code=201)
```

### Where to add notification calls

Go through the existing routes and add notification creation at the points listed below.
Only add a notification call **after** the main operation has succeeded — never before.

| Trigger point                        | Recipient(s)              | Type                    |
|--------------------------------------|---------------------------|-------------------------|
| Invitation created                   | Invited user              | `INVITATION_RECEIVED`   |
| Agreement accepted by a participant  | All other participants    | `AGREEMENT_ACCEPTED`    |
| Agreement declined by a participant  | Agreement creator         | `AGREEMENT_DECLINED`    |
| Condition added to agreement         | All participants          | `CONDITION_ADDED`       |
| Condition updated                    | All participants          | `CONDITION_UPDATED`     |
| All parties accepted (completed)     | All participants          | `AGREEMENT_COMPLETED`   |

---

## Error Handling

Use the existing `AppError` subclass pattern. Add these to the project's exceptions file:

```python
class NotificationNotFoundError(AppError):
    def __init__(self, message: str = "Notification not found"):
        super().__init__(message=message, code="NOT_FOUND", status_code=404)
```

No new exception handlers needed in `main.py` — the existing `AppError` handler
covers everything.

---

## Implementation Checklist

- [ ] Create the `Notification` SQLAlchemy model with all fields above
- [ ] Create the `NotificationType` enum
- [ ] Run and apply the database migration for the new table
- [ ] Create `repo.py` with all repo methods — ensure every query filters by `user_id`
- [ ] Create `service.py` wrapping the repo
- [ ] Create `schemas.py` with request and response models
- [ ] Create `dependencies.py` with `NotificationServiceDep` following existing dep patterns
- [ ] Create `router.py` with all four endpoints
- [ ] Register the notification router in the main app router
- [ ] Add `NotificationNotFoundError` to the project exceptions file
- [ ] Inject `NotificationServiceDep` into the agreement invitation route and create notifications for each invited participant
- [ ] Go through all other trigger points in the table above and add notification calls
- [ ] Verify all notification endpoints require authentication
- [ ] Verify that marking notifications as read filters by `user_id` so users cannot affect each other's notifications
