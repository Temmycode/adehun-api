import hmac
import json
import hashlib
from fastapi import APIRouter, Request, HTTPException, status, Header
from app.database import SessionDep
from app.dependencies import ActiveUserDep, WalletServiceDep
from app.exceptions import AppError
from app.rate_limiting import limiter
from app.core.response import (
    APIResponse,
    InternalServerErrorResponse,
    UnauthorizedResponse,
    success_response,
)
from app.logging import get_logger
from app.schemas.wallet_schema import WalletCodeResponse, WalletCreate
from app.config import settings
from app.models import PaystackTransaction, Wallet
from app.models.paystack_transaction import TransactionStatus

logger = get_logger(__name__)

router = APIRouter(
    prefix="/wallet",
    tags=["Wallet"],
    responses={500: {"model": InternalServerErrorResponse}},
)


@router.post(
    "/fund",
    response_model=APIResponse[WalletCodeResponse],
    responses={401: {"model": UnauthorizedResponse}},
)
@limiter.limit("10/minute")
async def fund_wallet(
    request: Request,
    wallet_data: WalletCreate,
    current_user: ActiveUserDep,
    wallet_service: WalletServiceDep,
):
    """Fund the user's wallet"""

    try:
        wallet_code_response = await wallet_service.request_wallet_fund(
            current_user.id, current_user.email, wallet_data
        )
        return success_response(data=wallet_code_response)
    except AppError as err:
        raise HTTPException(status_code=err.status_code, detail=err.message)


@router.post("/webhook/paystack")
async def paystack_webhook(
    request: Request,
    session: SessionDep,
    wallet_service: WalletServiceDep,
    x_paystack_signature: str = Header(None),
):
    # 1. Get the raw body (required for HMAC signature)
    raw_body = await request.body()

    # 2. Compute the HMAC SHA512 signature
    computed_signature = hmac.new(
        key=settings.paystack_test_secret_key.encode("utf-8"),
        msg=raw_body,
        digestmod=hashlib.sha512,
    ).hexdigest()

    # 3. Compare signatures
    if computed_signature != x_paystack_signature:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid signature"
        )

    # 4. Parse the JSON body safely now that it's verified
    payload = json.loads(raw_body)
    event_type = payload.get("event")

    if event_type != "charge.success":
        # Acknowledge other events immediately without processing
        return {"status": "success", "message": "Event ignored"}

    data = payload.get("data", {})
    transaction_reference = data.get("reference")
    amount_paid_kobo = data.get("amount")

    # 5. Look up the transaction in your database using the reference
    transaction = (
        session.query(PaystackTransaction)
        .filter_by(reference=transaction_reference)
        .first()
    )

    if not transaction:
        # Note: Always return 200 to Paystack even if you can't find it locally,
        # otherwise Paystack will keep spamming your server with retries.
        return {"status": "success", "message": "Transaction not found locally"}

    # Idempotency check: If it's already processed, ignore safely
    if transaction.status != TransactionStatus.PENDING:
        return {"status": "success", "message": "Already processed"}

    # 6. Verify the amount matches what you expected (protects against partial payments)
    # transaction.amount is in Naira (Decimal), Paystack amount is in Kobo (int)
    expected_kobo = int(transaction.amount * 100)
    if amount_paid_kobo < expected_kobo:
        transaction.status = TransactionStatus.FAILED
        transaction.gateway_response = "Underpaid"
        transaction.raw_webhook_data = payload
        session.add(transaction)
        session.commit()
        return {"status": "success", "message": "Underpayment recorded"}

    # 7. Update the transaction with Paystack's exact data
    transaction.status = TransactionStatus.SUCCESS
    transaction.paystack_id = data.get("id")
    transaction.payment_channel = data.get("channel")  # e.g., 'card'
    transaction.gateway_response = data.get("gateway_response")
    transaction.raw_webhook_data = payload

    # 8. Update the user's Escrow Wallet balance
    wallet_service.update_wallet_fund(transaction.amount, transaction.user_id)

    # 10. Return 200 OK fast so Paystack knows you received it
    return {"status": "success"}
