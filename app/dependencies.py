from typing import Annotated

from fastapi import Depends

from app.database import SessionDep
from app.models import User
from app.redis import RedisDep
from app.repository.user_repository import UserRepository
from app.service.auth_service import AuthService
from app.service.user_service import UserService
from app.token_service import get_active_user, get_current_user


def get_user_repository(session: SessionDep, redis: RedisDep) -> UserRepository:
    return UserRepository(session, redis)


UserRepositoryDep = Annotated[UserRepository, Depends(get_user_repository)]


def get_user_service(user_repository: UserRepositoryDep) -> UserService:
    return UserService(user_repository)


UserServiceDep = Annotated[UserService, Depends(get_user_service)]


CurrentUserDep = Annotated[User, Depends(get_current_user)]


ActiveUserDep = Annotated[User, Depends(get_active_user)]


def get_auth_service(user_repo: UserRepositoryDep):
    return AuthService(user_repo)


AuthServiceDep = Annotated[AuthService, Depends(get_auth_service)]
