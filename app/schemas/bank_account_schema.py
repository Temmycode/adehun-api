from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class BankResponse(BaseModel):
    """One entry from Paystack's bank list."""

    name: str
    code: str
    currency: str | None = None
    type: str | None = None


class AccountResolveRequest(BaseModel):
    account_number: str = Field(min_length=10, max_length=20)
    bank_code: str = Field(min_length=1, max_length=10)


class ResolvedAccountResponse(BaseModel):
    account_number: str
    account_name: str
    bank_code: str
    bank_name: str


class BankAccountCreate(BaseModel):
    """Note there is no `account_name` field, and there must never be one.

    The holder's name always comes from Paystack's resolve step; accepting it
    from the client would let a user label someone else's account as their own.
    """

    account_number: str = Field(min_length=10, max_length=20)
    bank_code: str = Field(min_length=1, max_length=10)
    make_default: bool = False


class BankAccountResponse(BaseModel):
    id: str
    account_number: str
    account_name: str
    bank_code: str
    bank_name: str
    currency: str
    is_default: bool
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
