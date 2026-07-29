import hashlib
import hmac
import json

from fastapi import APIRouter, Header, HTTPException, Request, WebSocket, status
from fastapi.responses import JSONResponse

from app.config import settings
from app.core.response import (
    APIResponse,
    BadRequestResponse,
    ConflictResponse,
    InternalServerErrorResponse,
    NotFoundResponse,
    UnauthorizedResponse,
    success_response,
)
from app.dependencies import (
    ActiveUserDep,
    IdempotencyDep,
    NotificationServiceDep,
    PaystackWebhookServiceDep,
    WalletServiceDep,
)
from app.logging import get_logger
from app.rate_limiting import limiter
from app.realtime.manager import ws_manager
from app.schemas.wallet_schema import (
    FundInitResponse,
    WalletBalanceResponse,
    WalletCreate,
    WithdrawalCreate,
    WithdrawalResponse,
)
from app.service.token_service import get_user_id_from_ws

logger = get_logger(__name__)

router = APIRouter(
    prefix="/wallet",
    tags=["Wallet"],
    responses={
        401: {"model": UnauthorizedResponse},
        500: {"model": InternalServerErrorResponse},
    },
)


@router.get("", response_model=APIResponse[WalletBalanceResponse])
@limiter.limit("30/minute")
async def get_wallet(
    request: Request,
    current_user: ActiveUserDep,
    wallet_service: WalletServiceDep,
):
    """Get the authenticated user's balances."""
    return success_response(data=wallet_service.get_balance(current_user.id))


@router.post(
    "/fund",
    status_code=201,
    response_model=APIResponse[FundInitResponse],
    responses={
        400: {"model": BadRequestResponse},
        409: {"model": ConflictResponse},
    },
)
@limiter.limit("10/minute")
async def fund_wallet(
    request: Request,
    wallet_data: WalletCreate,
    current_user: ActiveUserDep,
    wallet_service: WalletServiceDep,
    idem: IdempotencyDep,
):
    """Start funding the wallet.

    Requires an `Idempotency-Key` header — retrying with the same key replays
    the original response instead of creating a second Paystack transaction.
    The wallet is credited only when the `charge.success` webhook arrives.
    """
    replay = idem.begin("POST /wallet/fund", wallet_data)
    if replay is not None:
        return replay

    result = await wallet_service.request_wallet_fund(
        current_user.id, current_user.email, wallet_data
    )
    idem.bind_reference(result.reference)
    return idem.complete(success_response(data=result, status_code=201))


@router.post(
    "/withdraw",
    status_code=202,
    response_model=APIResponse[WithdrawalResponse],
    responses={
        400: {"model": BadRequestResponse},
        404: {"model": NotFoundResponse},
        409: {"model": ConflictResponse},
    },
)
@limiter.limit("5/minute")
async def withdraw(
    request: Request,
    payload: WithdrawalCreate,
    current_user: ActiveUserDep,
    wallet_service: WalletServiceDep,
    idem: IdempotencyDep,
):
    """Withdraw to a bank account.

    The balance is debited immediately and the transfer is sent to Paystack;
    the final outcome arrives by webhook, so this returns 202 with a pending
    status. A failed or reversed transfer credits the money back automatically.

    Requires an `Idempotency-Key` header.
    """
    replay = idem.begin("POST /wallet/withdraw", payload)
    if replay is not None:
        return replay

    result = await wallet_service.request_withdrawal(current_user.id, payload)
    idem.bind_reference(result.reference)
    return idem.complete(success_response(data=result, status_code=202))


@router.get(
    "/withdrawals/{reference}",
    response_model=APIResponse[WithdrawalResponse],
    responses={404: {"model": NotFoundResponse}},
)
@limiter.limit("30/minute")
async def get_withdrawal(
    request: Request,
    reference: str,
    current_user: ActiveUserDep,
    wallet_service: WalletServiceDep,
):
    """Check a withdrawal.

    If it is still pending, this asks Paystack directly rather than waiting on
    the webhook — a transfer whose initiate call timed out would otherwise sit
    pending indefinitely.
    """
    return success_response(
        data=await wallet_service.get_withdrawal(current_user.id, reference)
    )


@router.websocket("/ws")
async def wallet_websocket(websocket: WebSocket, wallet_service: WalletServiceDep):
    user_id = get_user_id_from_ws(websocket)
    if not user_id:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    await ws_manager.connect(user_id, websocket)
    await websocket.send_json(wallet_service.get_wallet_state_for_ws(user_id))

    try:
        while True:
            await websocket.receive_text()
    except Exception:
        ws_manager.disconnect(user_id, websocket)


# ---------------------------------------------------------------------------
# Webhook
# ---------------------------------------------------------------------------


def _verify_paystack_signature(raw_body: bytes, provided: str | None) -> bool:
    """Constant-time HMAC-SHA512 check over the exact bytes received.

    Both the test and live secrets are tried so the two environments can share
    an endpoint.
    """
    if not provided:
        return False
    for secret in settings.paystack_webhook_secrets:
        computed = hmac.new(
            secret.encode("utf-8"), raw_body, hashlib.sha512
        ).hexdigest()
        if hmac.compare_digest(computed, provided):
            return True
    return False


@router.post("/webhook/paystack", include_in_schema=False)
async def paystack_webhook(
    request: Request,
    webhook_service: PaystackWebhookServiceDep,
    notification_service: NotificationServiceDep,
    x_paystack_signature: str = Header(default=None),
):
    # The signature is over the raw bytes, so read the body before parsing.
    raw_body = await request.body()

    if not _verify_paystack_signature(raw_body, x_paystack_signature):
        logger.warning(
            "paystack signature verification failed",
            extra={"body_size": len(raw_body)},
        )
        raise HTTPException(status_code=401, detail="Invalid signature")

    try:
        payload = json.loads(raw_body)
    except ValueError:
        # Correctly signed but unparseable. Retrying will never help.
        logger.error("paystack webhook body is not valid JSON")
        return JSONResponse(
            status_code=200, content={"status": "ignored", "reason": "malformed"}
        )

    outcome = await webhook_service.handle(payload, raw_body)

    # Cross-feature side effects are fired here, not inside the service — see
    # the orchestration rule in CLAUDE.md. Neither may fail the webhook.
    for intent in outcome.notifications:
        try:
            notification_service.create_notification(**intent.as_kwargs())
        except Exception:
            logger.exception(
                "failed to create webhook notification",
                extra={"event_type": outcome.event_type},
            )

    for event in outcome.ws_events:
        try:
            await ws_manager.send_to_user(event.user_id, event.payload)
        except Exception:
            logger.exception(
                "failed to push websocket event",
                extra={"event_type": outcome.event_type},
            )

    return JSONResponse(
        status_code=outcome.http_status, content={"status": outcome.status}
    )
