import uuid
from decimal import Decimal
import httpx
from app.exceptions import AppError
from app.repository.wallet_repository import WalletRepository
from app.config import settings
from app.schemas.wallet_schema import WalletCodeResponse, WalletCreate

BASE_URL = "https://api.paystack.co"
headers = {
    "Authorization": f"Bearer {settings.paystack_test_secret_key}",
    "Content-Type": "application/json",
}


def generate_fund_reference(user_id: str) -> str:
    random_hash = uuid.uuid4().hex[:8]
    return f"ESC_{user_id}_{random_hash}"


class WalletService:
    def __init__(self, wallet_repo: WalletRepository):
        self.wallet_repo = wallet_repo

    async def request_wallet_fund(
        self, user_id: str, user_email: str, wallet_data: WalletCreate
    ):
        """Fund the user's wallet"""
        url = f"{BASE_URL}/transaction/initialize"
        amount_in_kobo = int(wallet_data.amount * 100)
        payload = {
            "email": user_email,
            "amount": amount_in_kobo,
            "reference": generate_fund_reference(user_id),
        }

        async with httpx.AsyncClient() as client:
            response = await client.post(url, json=payload, headers=headers)
            data = response.json()

            if response.status_code == 200 and data.get("status"):
                return WalletCodeResponse(access_code=data["data"]["access_code"])

            raise AppError(
                message="Paystack Init Error: {data.get('message')}",
                code="BAD_REQUEST",
                status_code=401,
            )

    def update_wallet_fund(self, amount: Decimal, user_id: str):
        return self.wallet_repo.update_wallet_amount(amount, user_id)
