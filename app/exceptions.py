class AppError(Exception):
    def __init__(self, message: str, code: str, status_code: int):
        super().__init__(message)
        self.message = message
        self.code = code
        self.status_code = status_code


# 400s
class BadRequestError(AppError):
    def __init__(self, message: str = "Bad request"):
        super().__init__(message=message, code="BAD_REQUEST", status_code=400)


# 403s
class ForbiddenError(AppError):
    def __init__(self, message: str = "Access is forbidden"):
        super().__init__(message=message, code="FORBIDDEN", status_code=403)


# 404s
class UserNotFoundError(AppError):
    def __init__(self, message: str = "User not found"):
        super().__init__(message=message, code="NOT_FOUND", status_code=404)


class AgreementNotFoundError(AppError):
    def __init__(self, message: str = "Agreement not found"):
        super().__init__(message=message, code="NOT_FOUND", status_code=404)


class InvitationNotFoundError(AppError):
    def __init__(self, message: str = "Invalid or expired invitation token"):
        super().__init__(message=message, code="NOT_FOUND", status_code=404)


class ConditionNotFoundError(AppError):
    def __init__(self, message: str = "Condition not found"):
        super().__init__(message=message, code="NOT_FOUND", status_code=404)


class ParticipantNotFoundError(AppError):
    def __init__(self, message: str = "Participant not found in agreement"):
        super().__init__(message=message, code="NOT_FOUND", status_code=404)


class NotificationNotFoundError(AppError):
    def __init__(self, message: str = "Notification not found"):
        super().__init__(message=message, code="NOT_FOUND", status_code=404)


# 409s
class UserAlreadyExistsError(AppError):
    def __init__(self, message: str = "User already exists"):
        super().__init__(message=message, code="CONFLICT", status_code=409)


class AgreementAlreadyExistsError(AppError):
    def __init__(self, message: str = "Agreement already exists"):
        super().__init__(message=message, code="CONFLICT", status_code=409)


# 500s
class AgreementCreationError(AppError):
    def __init__(self, message: str = "Failed to create agreement"):
        super().__init__(message=message, code="INTERNAL_SERVER_ERROR", status_code=500)


class ConditionSaveError(AppError):
    def __init__(self, message: str = "Failed to save condition"):
        super().__init__(message=message, code="INTERNAL_SERVER_ERROR", status_code=500)


class AgreementAcceptanceError(AppError):
    def __init__(self, message: str = "Failed to accept agreement"):
        super().__init__(message=message, code="INTERNAL_SERVER_ERROR", status_code=500)


class AssetUploadError(AppError):
    def __init__(self, message: str = "Failed to upload asset"):
        super().__init__(message=message, code="INTERNAL_SERVER_ERROR", status_code=500)


class AssetRetrievalError(AppError):
    def __init__(self, message: str = "Failed to retrieve assets"):
        super().__init__(message=message, code="INTERNAL_SERVER_ERROR", status_code=500)
