from typing import Annotated

from fastapi import Depends

from app.database import SessionDep
from app.redis import RedisDep
from app.repository.user_repository import UserRepository
from app.service.user_service import UserService


def get_user_repository(session: SessionDep, redis: RedisDep) -> UserRepository:
    return UserRepository(session, redis)


UserRepositoryDep = Annotated[UserRepository, Depends(get_user_repository)]


def get_user_service(user_repository: UserRepositoryDep) -> UserService:
    return UserService(user_repository)


UserServiceDep = Annotated[UserService, Depends(get_user_service)]
