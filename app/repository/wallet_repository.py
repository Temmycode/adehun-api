from redis import Redis
from decimal import Decimal
from app.core.response import NotFoundResponse
from app.exceptions import WalletNotFoundError
from app.logging import get_logger
from sqlmodel import Session, select
from app.redis import RedisClient
from app.models import Wallet

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# TTL constants (seconds)
# ---------------------------------------------------------------------------
_TTL_USER_WALLET = 60 * 5  # 5 minutes – cache TTL


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _user_wallet_key(user_id: str) -> str:
    return f"user:{user_id}:wallet"


# ---------------------------------------------------------------------------
# Repository
# ---------------------------------------------------------------------------


class WalletRepository(RedisClient):
    def __init__(self, session: Session, client: Redis | None):
        self.session = session
        super().__init__(client)

    def get_user_wallet(self, user_id: str) -> Wallet | None:
        key = _user_wallet_key(user_id)
        cache = self._cache_get(key)
        if cache is not None:
            logger.debug("cache hit for user wallet", extra={"user_id": user_id})
            return Wallet.model_validate(cache)

        wallet = self.session.exec(
            select(Wallet).where(Wallet.user_id == user_id)
        ).first()
        if wallet:
            self._cache_set(key, wallet, _TTL_USER_WALLET)
        else:
            logger.info("user wallet not found", extra={"user_id": user_id})
        return wallet

    def update_wallet_amount(self, amount: Decimal, user_id: str) -> Wallet:
        key = _user_wallet_key(user_id)
        user_wallet = self.get_user_wallet(user_id)

        if user_wallet is None:
            # Create a wallet for the user
            user_wallet = Wallet(user_id=user_id, amount=amount)
        else:
            user_wallet.escrow_balance = user_wallet.escrow_balance + amount

        self.session.add(user_wallet)
        self.session.commit()
        self.session.refresh(user_wallet)

        self._cache_set(key, user_wallet, _TTL_USER_WALLET)
        return user_wallet

    def transfer_to_other_account(self, user_id: str, amount: Decimal) -> Wallet:
        key = _user_wallet_key(user_id)
        user_wallet = self.get_user_wallet(user_id)

        if user_wallet is None:
            raise WalletNotFoundError()

        user_wallet.escrow_balance = user_wallet.escrow_balance - amount

        self.session.add(user_wallet)
        self.session.commit()
        self.session.refresh(user_wallet)
        self._cache_set(key, user_wallet, _TTL_USER_WALLET)

        return user_wallet
