"""Bank accounts and Paystack transfer recipients."""

from app.exceptions import (
    BadRequestError,
    BankAccountNotFoundError,
    DuplicateBankAccountError,
)
from app.logging import get_logger
from app.models import BankAccount
from app.repository.bank_account_repository import BankAccountRepository
from app.schemas.bank_account_schema import (
    AccountResolveRequest,
    BankAccountCreate,
    BankAccountResponse,
    BankResponse,
    ResolvedAccountResponse,
)
from app.service.paystack_client import paystack_client

logger = get_logger(__name__)


class BankAccountService:
    def __init__(self, bank_account_repo: BankAccountRepository):
        self.bank_account_repo = bank_account_repo

    async def list_banks(self, currency: str = "NGN") -> list[BankResponse]:
        """Paystack's bank list, cached for a day — it is huge and near-static."""
        cached = self.bank_account_repo.get_cached_banks(currency)
        if cached is not None:
            return [BankResponse(**bank) for bank in cached]

        banks = await paystack_client.list_banks(currency=currency)
        trimmed = [
            {
                "name": b["name"],
                "code": b["code"],
                "currency": b.get("currency"),
                "type": b.get("type"),
            }
            for b in banks
        ]
        self.bank_account_repo.cache_banks(currency, trimmed)
        return [BankResponse(**bank) for bank in trimmed]

    async def resolve_account(
        self, payload: AccountResolveRequest
    ) -> ResolvedAccountResponse:
        """Ask Paystack who owns an account number."""
        data = await paystack_client.resolve_account_number(
            account_number=payload.account_number, bank_code=payload.bank_code
        )
        return ResolvedAccountResponse(
            account_number=data["account_number"],
            account_name=data["account_name"],
            bank_code=payload.bank_code,
            bank_name=await self._bank_name(payload.bank_code),
        )

    async def _bank_name(self, bank_code: str) -> str:
        for bank in await self.list_banks():
            if bank.code == bank_code:
                return bank.name
        raise BadRequestError("Unknown bank code")

    def get_user_bank_accounts(self, user_id: str) -> list[BankAccountResponse]:
        return [
            BankAccountResponse.model_validate(a)
            for a in self.bank_account_repo.list_for_user(user_id)
        ]

    async def add_bank_account(
        self, user_id: str, user_name: str, payload: BankAccountCreate
    ) -> BankAccountResponse:
        """Resolve, register a Paystack recipient, then persist.

        The account holder's name comes from Paystack, never from the client —
        otherwise a user could label someone else's account as their own.
        """
        duplicate = self.bank_account_repo.find_active_duplicate(
            user_id, payload.bank_code, payload.account_number
        )
        if duplicate is not None:
            raise DuplicateBankAccountError()

        bank_name = await self._bank_name(payload.bank_code)
        resolved = await paystack_client.resolve_account_number(
            account_number=payload.account_number, bank_code=payload.bank_code
        )
        account_name = resolved["account_name"]

        recipient = await paystack_client.create_transfer_recipient(
            name=account_name,
            account_number=payload.account_number,
            bank_code=payload.bank_code,
        )

        account = BankAccount(
            user_id=user_id,
            account_number=payload.account_number,
            bank_code=payload.bank_code,
            bank_name=bank_name,
            account_name=account_name,
            recipient_code=recipient["recipient_code"],
        )

        # The first account a user adds is their default, whatever they asked for.
        make_default = payload.make_default or (
            self.bank_account_repo.get_default_for_user(user_id) is None
        )
        self.bank_account_repo.add(account, commit=not make_default)
        if make_default:
            self.bank_account_repo.set_default(account)

        logger.info(
            "bank account added",
            extra={
                "user_id": user_id,
                "bank_code": payload.bank_code,
                "is_default": account.is_default,
            },
        )
        return BankAccountResponse.model_validate(account)

    def set_default_bank_account(
        self, bank_account_id: str, user_id: str
    ) -> BankAccountResponse:
        account = self.bank_account_repo.get_for_user(bank_account_id, user_id)
        if account is None:
            raise BankAccountNotFoundError()
        return BankAccountResponse.model_validate(
            self.bank_account_repo.set_default(account)
        )

    def remove_bank_account(self, bank_account_id: str, user_id: str) -> None:
        """Soft delete — ledger rows and payout records still reference it."""
        account = self.bank_account_repo.get_for_user(bank_account_id, user_id)
        if account is None:
            raise BankAccountNotFoundError()
        if self.bank_account_repo.has_pending_withdrawal(account.id):
            raise BadRequestError(
                "This account has a withdrawal in progress and cannot be removed yet"
            )
        self.bank_account_repo.deactivate(account)
