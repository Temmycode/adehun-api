from typing import Annotated

from fastapi import Depends, Header

from app.core.idempotency import IdempotencyContext
from app.database import SessionDep
from app.models import User
from app.redis import RedisDep
from app.repository.agreement_repository import AgreementRepository
from app.repository.asset_repository import AssetRepository
from app.repository.bank_account_repository import BankAccountRepository
from app.repository.condition_repository import ConditionRepository
from app.repository.idempotency_repository import IdempotencyRepository
from app.repository.notification_repository import NotificationRepository
from app.repository.stats_repository import StatsRepository
from app.repository.transaction_repository import TransactionRepository
from app.repository.user_repository import UserRepository
from app.repository.wallet_repository import WalletRepository
from app.repository.webhook_event_repository import WebhookEventRepository
from app.service.agreement_service import AgreementService
from app.service.asset_service import AssetService
from app.service.auth_service import AuthService
from app.service.bank_account_service import BankAccountService
from app.service.condition_service import ConditionService
from app.service.notification_service import NotificationService
from app.service.paystack_webhook_service import PaystackWebhookService
from app.service.stats_service import StatsService
from app.service.transaction_service import TransactionService
from app.service.user_service import UserService
from app.service.wallet_service import WalletService
from app.service.token_service import get_active_user, get_current_user


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


def get_wallet_repository(session: SessionDep, client: RedisDep) -> WalletRepository:
    return WalletRepository(session, client)


WalletRepositoryDep = Annotated[WalletRepository, Depends(get_wallet_repository)]


def get_bank_account_repository(
    session: SessionDep, client: RedisDep
) -> BankAccountRepository:
    return BankAccountRepository(session, client)


BankAccountRepositoryDep = Annotated[
    BankAccountRepository, Depends(get_bank_account_repository)
]


def get_bank_account_service(repo: BankAccountRepositoryDep) -> BankAccountService:
    return BankAccountService(repo)


BankAccountServiceDep = Annotated[
    BankAccountService, Depends(get_bank_account_service)
]


def get_wallet_service(
    repo: WalletRepositoryDep, bank_account_repo: BankAccountRepositoryDep
) -> WalletService:
    return WalletService(repo, bank_account_repo)


WalletServiceDep = Annotated[WalletService, Depends(get_wallet_service)]


def get_transaction_repository(
    session: SessionDep, client: RedisDep
) -> TransactionRepository:
    return TransactionRepository(session, client)


TransactionRepositoryDep = Annotated[
    TransactionRepository, Depends(get_transaction_repository)
]


def get_transaction_service(repo: TransactionRepositoryDep) -> TransactionService:
    return TransactionService(repo)


TransactionServiceDep = Annotated[
    TransactionService, Depends(get_transaction_service)
]


def get_webhook_event_repository(
    session: SessionDep, client: RedisDep
) -> WebhookEventRepository:
    return WebhookEventRepository(session, client)


WebhookEventRepositoryDep = Annotated[
    WebhookEventRepository, Depends(get_webhook_event_repository)
]


def get_paystack_webhook_service(
    wallet_repo: WalletRepositoryDep, webhook_repo: WebhookEventRepositoryDep
) -> PaystackWebhookService:
    return PaystackWebhookService(wallet_repo, webhook_repo)


PaystackWebhookServiceDep = Annotated[
    PaystackWebhookService, Depends(get_paystack_webhook_service)
]


def get_idempotency_repository(
    session: SessionDep, client: RedisDep
) -> IdempotencyRepository:
    return IdempotencyRepository(session, client)


IdempotencyRepositoryDep = Annotated[
    IdempotencyRepository, Depends(get_idempotency_repository)
]


def get_idempotency_context(
    repo: IdempotencyRepositoryDep,
    current_user: ActiveUserDep,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
):
    """Yield dependency: the teardown releases a reservation the handler abandoned."""
    context = IdempotencyContext(repo, current_user.id, idempotency_key)
    try:
        yield context
    finally:
        context.release_if_abandoned()


IdempotencyDep = Annotated[IdempotencyContext, Depends(get_idempotency_context)]
