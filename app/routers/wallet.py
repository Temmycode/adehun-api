import hmac
import json
import hashlib
from fastapi import APIRouter, Request, HTTPException, WebSocket, status, Header
from app.dependencies import ActiveUserDep, WalletServiceDep
from app.exceptions import AppError
from app.core.response import (
    APIResponse,
    InternalServerErrorResponse,
    UnauthorizedResponse,
    success_response,
)
from app.rate_limiting import limiter
from app.logging import get_logger
from app.schemas.wallet_schema import WalletCodeResponse, WalletCreate
from app.config import settings
from app.service.token_service import get_user_id_from_ws
from app.realtime.manager import ws_manager
from app.exceptions import PaystackTransactionNotFoundError


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


@router.websocket("/ws")
async def wallet_websocket(websocket: WebSocket, wallet_service: WalletServiceDep):
    user_id = get_user_id_from_ws(websocket)
    if not user_id:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    await ws_manager.connect(user_id, websocket)

    wallet_data = wallet_service.get_wallet_data(user_id)

    await websocket.send_json(wallet_data)

    try:
        while True:
            await websocket.receive_text()

    except Exception:
        ws_manager.disconnect(user_id, websocket)


@router.post("/webhook/paystack")
async def paystack_webhook(
    request: Request,
    wallet_service: WalletServiceDep,
    x_paystack_signature: str = Header(None),
):
    logger.info("paystack webhook received")

    # 1. Get the raw body (required for HMAC signature)
    raw_body = await request.body()

    logger.debug(
        "received webhook body",
        extra={
            "body_size": len(raw_body),
            "signature_present": x_paystack_signature is not None,
        },
    )

    # 2. Compute the HMAC SHA512 signature
    computed_signature = hmac.new(
        key=settings.paystack_test_secret_key.encode("utf-8"),
        msg=raw_body,
        digestmod=hashlib.sha512,
    ).hexdigest()

    logger.debug("computed webhook signature")

    # 3. Compare signatures
    if computed_signature != x_paystack_signature:
        logger.warning(
            "paystack signature verification failed",
            extra={
                "body_size": len(raw_body),
            },
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid signature",
        )

    logger.info("paystack signature verified")

    # 4. Parse the JSON body safely now that it's verified
    try:
        payload = json.loads(raw_body)
    except Exception:
        logger.exception("failed to parse paystack webhook payload")
        raise

    event_type = payload.get("event")
    reference = payload.get("data", {}).get("reference")

    logger.info(
        "paystack event received",
        extra={
            "event_type": event_type,
            "reference": reference,
        },
    )

    if event_type != "charge.success":
        logger.debug(
            "ignoring paystack event",
            extra={
                "event_type": event_type,
                "reference": reference,
            },
        )
        return {"status": "success", "message": "Event ignored"}

    logger.info(
        "processing charge.success event",
        extra={
            "reference": reference,
        },
    )

    try:
        await wallet_service.update_wallet_fund(payload)

        logger.info(
            "wallet updated successfully",
            extra={
                "reference": reference,
            },
        )
    except PaystackTransactionNotFoundError:
        logger.warning(
            "paystack transaction not found locally",
            extra={
                "reference": reference,
            },
        )
        return {
            "status": "success",
            "message": "Transaction not found locally",
        }
    except Exception:
        logger.exception(
            "unexpected error while processing paystack webhook",
            extra={
                "reference": reference,
            },
        )
        raise

    logger.info(
        "paystack webhook processed successfully",
        extra={
            "reference": reference,
            "event_type": event_type,
        },
    )

    return {"status": "success"}
