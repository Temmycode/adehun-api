"""Payout destinations. Every query is scoped by `user_id`."""

from datetime import datetime, timezone

from redis import Redis
from sqlmodel import Session, select

from app.logging import get_logger
from app.models import BankAccount, PaystackTransaction
from app.models.paystack_transaction import TransactionStatus
from app.redis import RedisClient

logger = get_logger(__name__)

_TTL_BANK_LIST = 60 * 60 * 24  # 24 hours — the bank list is large and static
_BANK_LIST_KEY = "paystack:banks"


def _bank_list_key(currency: str) -> str:
    return f"{_BANK_LIST_KEY}:{currency}"


class BankAccountRepository(RedisClient):
    def __init__(self, session: Session, redis_client: Redis | None):
        super().__init__(redis_client)
        self.session = session

    # ------------------------------------------------------------------ #
    #  Bank list cache                                                   #
    # ------------------------------------------------------------------ #

    def get_cached_banks(self, currency: str) -> list[dict] | None:
        return self._cache_get(_bank_list_key(currency))

    def cache_banks(self, currency: str, banks: list[dict]) -> None:
        self._cache_set(_bank_list_key(currency), banks, _TTL_BANK_LIST)

    # ------------------------------------------------------------------ #
    #  Accounts                                                          #
    # ------------------------------------------------------------------ #

    def list_for_user(self, user_id: str) -> list[BankAccount]:
        results = self.session.exec(
            select(BankAccount)
            .where(BankAccount.user_id == user_id, BankAccount.is_active == True)  # noqa: E712
            .order_by(
                BankAccount.is_default.desc(),  # pyright: ignore[reportAttributeAccessIssue]
                BankAccount.created_at.desc(),  # pyright: ignore[reportAttributeAccessIssue]
            )
        ).all()
        return list(results)

    def get_for_user(self, bank_account_id: str, user_id: str) -> BankAccount | None:
        return self.session.exec(
            select(BankAccount).where(
                BankAccount.id == bank_account_id,
                BankAccount.user_id == user_id,
                BankAccount.is_active == True,  # noqa: E712
            )
        ).first()

    def get_default_for_user(self, user_id: str) -> BankAccount | None:
        return self.session.exec(
            select(BankAccount).where(
                BankAccount.user_id == user_id,
                BankAccount.is_default == True,  # noqa: E712
                BankAccount.is_active == True,  # noqa: E712
            )
        ).first()

    def find_active_duplicate(
        self, user_id: str, bank_code: str, account_number: str
    ) -> BankAccount | None:
        return self.session.exec(
            select(BankAccount).where(
                BankAccount.user_id == user_id,
                BankAccount.bank_code == bank_code,
                BankAccount.account_number == account_number,
                BankAccount.is_active == True,  # noqa: E712
            )
        ).first()

    def add(self, bank_account: BankAccount, *, commit: bool = True) -> BankAccount:
        self.session.add(bank_account)
        if commit:
            self.session.commit()
            self.session.refresh(bank_account)
        return bank_account

    def set_default(self, bank_account: BankAccount) -> BankAccount:
        """Make one account the default, clearing any other.

        Both statements are in one transaction: `ux_bank_account_one_default`
        would reject the new default if the old one were still set.
        """
        now = datetime.now(timezone.utc)
        current = self.get_default_for_user(bank_account.user_id)
        if current is not None and current.id != bank_account.id:
            current.is_default = False
            current.updated_at = now
            self.session.add(current)
            self.session.flush()

        bank_account.is_default = True
        bank_account.updated_at = now
        self.session.add(bank_account)
        self.session.commit()
        self.session.refresh(bank_account)
        return bank_account

    def deactivate(self, bank_account: BankAccount) -> BankAccount:
        """Soft delete — ledger rows and paystack_transaction reference this."""
        bank_account.is_active = False
        bank_account.is_default = False
        bank_account.updated_at = datetime.now(timezone.utc)
        self.session.add(bank_account)
        self.session.commit()
        self.session.refresh(bank_account)
        return bank_account

    def has_pending_withdrawal(self, bank_account_id: str) -> bool:
        """A payout in flight pins the account it is going to."""
        return (
            self.session.exec(
                select(PaystackTransaction.id).where(
                    PaystackTransaction.bank_account_id == bank_account_id,
                    PaystackTransaction.status == TransactionStatus.PENDING,
                )
            ).first()
            is not None
        )

    def rollback(self) -> None:
        self.session.rollback()
