from decimal import Decimal

from pydantic import BaseModel


class WalletCreate(BaseModel):
    amount: Decimal
    channel: str


class WalletCodeResponse(BaseModel):
    access_code: str
