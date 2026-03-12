class UserNotFound(Exception):
    def __init__(self, message="User not found"):
        self.message = message
        super().__init__(self.message)


class UserAlreadyExists(Exception): ...


class AgreementNotFoundError(Exception):
    def __init__(self, message="Agreement not found"):
        self.message = message
        super().__init__(self.message)


class AgreementAlreadyExistsError(Exception):
    def __init__(self, message="Agreement already exists"):
        self.message = message
        super().__init__(self.message)


class AgreementCreationError(Exception):
    def __init__(self, message="Failed to create agreement"):
        self.message = message
        super().__init__(self.message)


class InvitationNotFoundError(Exception):
    def __init__(self, message="Invalid or expired invitation token"):
        self.message = message
        super().__init__(self.message)
