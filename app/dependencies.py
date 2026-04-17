from typing import Annotated

from fastapi import Depends

from app.database import SessionDep
from app.models import User
from app.redis import RedisDep
from app.repository.agreement_repository import AgreementRepository
from app.repository.asset_repository import AssetRepository
from app.repository.condition_repository import ConditionRepository
from app.repository.notification_repository import NotificationRepository
from app.repository.stats_repository import StatsRepository
from app.repository.user_repository import UserRepository
from app.service.agreement_service import AgreementService
from app.service.asset_service import AssetService
from app.service.auth_service import AuthService
from app.service.condition_service import ConditionService
from app.service.notification_service import NotificationService
from app.service.stats_service import StatsService
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


def get_agreement_repository(
    session: SessionDep, redis_client: RedisDep
) -> AgreementRepository:
    return AgreementRepository(session, redis_client)


AgreementRepositoryDep = Annotated[
    AgreementRepository, Depends(get_agreement_repository)
]


def get_condition_repository(
    session: SessionDep, redis_client: RedisDep
) -> ConditionRepository:
    return ConditionRepository(session, redis_client)


ConditionRepositoryDep = Annotated[
    ConditionRepository, Depends(get_condition_repository)
]


def get_asset_repository(session: SessionDep, redis: RedisDep) -> AssetRepository:
    return AssetRepository(session, redis)


AssetRepositoryDep = Annotated[AssetRepository, Depends(get_asset_repository)]


def get_asset_service(repo: AssetRepositoryDep) -> AssetService:
    return AssetService(repo)


AssetServiceDep = Annotated[AssetService, Depends(get_asset_service)]


def get_agreement_service(agreement_repo: AgreementRepositoryDep) -> AgreementService:
    return AgreementService(agreement_repo)


AgreementServiceDep = Annotated[AgreementService, Depends(get_agreement_service)]


def get_condition_service(condition_repo: ConditionRepositoryDep) -> ConditionService:
    return ConditionService(condition_repo)


ConditionServiceDep = Annotated[ConditionService, Depends(get_condition_service)]


def get_stats_repository(session: SessionDep) -> StatsRepository:
    return StatsRepository(session)


StatsRepositoryDep = Annotated[StatsRepository, Depends(get_stats_repository)]


def get_stats_service(stats_repo: StatsRepositoryDep) -> StatsService:
    return StatsService(stats_repo)


StatsServiceDep = Annotated[StatsService, Depends(get_stats_service)]


def get_notification_repository(
    session: SessionDep, redis_client: RedisDep
) -> NotificationRepository:
    return NotificationRepository(session, redis_client)


NotificationRepositoryDep = Annotated[
    NotificationRepository, Depends(get_notification_repository)
]


def get_notification_service(
    notification_repo: NotificationRepositoryDep,
) -> NotificationService:
    return NotificationService(notification_repo)


NotificationServiceDep = Annotated[
    NotificationService, Depends(get_notification_service)
]
