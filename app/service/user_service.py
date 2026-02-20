from app.repository.user_repository import UserRepository


class UserService:
    def __init__(self, repository: UserRepository):
        self.repository = repository
