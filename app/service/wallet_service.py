import uuid
import httpx
from app.exceptions import AppError, PaystackTransactionNotFoundError
from app.repository.wallet_repository import WalletRepository
from app.config import settings
from app.schemas.wallet_schema import WalletCodeResponse, WalletCreate
from app.realtime.manager import ws_manager
from app.models.paystack_transaction import TransactionStatus

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

    async def update_wallet_fund(self, payload: dict):
        data = payload.get("data", {})
        transaction_reference = data.get("reference")
        amount_paid_kobo = data.get("amount")

        transaction = self.wallet_repo.get_paystack_transaction(transaction_reference)

        if not transaction:
            raise PaystackTransactionNotFoundError()

        if transaction.status != TransactionStatus.PENDING:
            return {"status": "success", "message": "Already processed"}

        expected_kobo = int(transaction.amount * 100)
        if amount_paid_kobo < expected_kobo:
            transaction.status = TransactionStatus.FAILED
            transaction.gateway_response = "Underpaid"
            transaction.raw_webhook_data = payload
            self.wallet_repo.add(transaction)
            self.wallet_repo.flush()
            return {"status": "success", "message": "Underpayment recorded"}

        # 7. Update the transaction with Paystack's exact data
        transaction.status = TransactionStatus.SUCCESS
        transaction.paystack_id = data.get("id")
        transaction.payment_channel = data.get("channel")  # e.g., 'card'
        transaction.gateway_response = data.get("gateway_response")
        transaction.raw_webhook_data = payload

        wallet = self.wallet_repo.update_wallet_amount(
            transaction.amount, transaction.user_id
        )
        await ws_manager.send_to_user(
            transaction.user_id,
            {
                "type": "WALLET_CREDITED",
                "amount": float(transaction.amount),
                "new_balance": float(wallet.escrow_balance),
            },
        )
