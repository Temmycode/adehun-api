class UserNotFound(Exception):
    def __init__(self, message="User not found"):
        self.message = message
        super().__init__(self.message)


class UserAlreadyExists(Exception): ...


class AgreementNotFound(Exception): ...


class AgreementAlreadyExists(Exception): ...


class AgreementCreationError(Exception):
    def __init__(self, message="Failed to create agreement"):
        self.message = message
        super().__init__(self.message)
