from decimal import Decimal

from pydantic import BaseModel


class AgreementCreate(BaseModel):
    # Agreement Participants
    user_ids: list[str] = []
    # Agreement Data
    description: str
    # Transaction Data
    amount: Decimal
