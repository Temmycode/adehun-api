from decimal import Decimal

from pydantic import BaseModel


class EscrowMovementResponse(BaseModel):
    """The result of funding or releasing an agreement's escrow."""

    agreement_id: str
    amount: Decimal
    reference: str
    available_balance: Decimal
    escrow_balance: Decimal
    replayed: bool = False
