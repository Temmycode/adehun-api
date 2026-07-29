from fastapi import APIRouter, Request

from app.core.response import (
    APIResponse,
    BadRequestResponse,
    ConflictResponse,
    InternalServerErrorResponse,
    NotFoundResponse,
    UnauthorizedResponse,
    success_response,
)
from app.dependencies import ActiveUserDep, BankAccountServiceDep
from app.rate_limiting import limiter
from app.schemas.bank_account_schema import (
    AccountResolveRequest,
    BankAccountCreate,
    BankAccountResponse,
    BankResponse,
    ResolvedAccountResponse,
)

router = APIRouter(
    prefix="/bank-accounts",
    tags=["Bank Accounts"],
    responses={
        401: {"model": UnauthorizedResponse},
        500: {"model": InternalServerErrorResponse},
    },
)


@router.get("/banks", response_model=APIResponse[list[BankResponse]])
@limiter.limit("20/minute")
async def list_banks(
    request: Request,
    _: ActiveUserDep,
    bank_account_service: BankAccountServiceDep,
    currency: str = "NGN",
):
    """List supported banks. Cached for 24 hours."""
    return success_response(data=await bank_account_service.list_banks(currency))


@router.post(
    "/resolve",
    response_model=APIResponse[ResolvedAccountResponse],
    responses={400: {"model": BadRequestResponse}},
)
@limiter.limit("10/minute")
async def resolve_account(
    request: Request,
    payload: AccountResolveRequest,
    _: ActiveUserDep,
    bank_account_service: BankAccountServiceDep,
):
    """Look up the holder of an account number before saving it.

    Rate limited tightly — Paystack bills per resolve in live mode.
    """
    return success_response(data=await bank_account_service.resolve_account(payload))


@router.get("", response_model=APIResponse[list[BankAccountResponse]])
@limiter.limit("30/minute")
async def get_bank_accounts(
    request: Request,
    current_user: ActiveUserDep,
    bank_account_service: BankAccountServiceDep,
):
    """List the authenticated user's saved payout accounts."""
    return success_response(
        data=bank_account_service.get_user_bank_accounts(current_user.id)
    )


@router.post(
    "",
    status_code=201,
    response_model=APIResponse[BankAccountResponse],
    responses={
        400: {"model": BadRequestResponse},
        409: {"model": ConflictResponse},
    },
)
@limiter.limit("5/minute")
async def add_bank_account(
    request: Request,
    payload: BankAccountCreate,
    current_user: ActiveUserDep,
    bank_account_service: BankAccountServiceDep,
):
    """Save a payout account.

    The holder's name is resolved server-side from Paystack, never taken from
    the request. The first account a user saves becomes their default.
    """
    return success_response(
        data=await bank_account_service.add_bank_account(
            current_user.id, current_user.name, payload
        ),
        status_code=201,
    )


@router.patch(
    "/{bank_account_id}/default",
    response_model=APIResponse[BankAccountResponse],
    responses={404: {"model": NotFoundResponse}},
)
@limiter.limit("10/minute")
async def set_default_bank_account(
    request: Request,
    bank_account_id: str,
    current_user: ActiveUserDep,
    bank_account_service: BankAccountServiceDep,
):
    """Make this the account withdrawals go to by default."""
    return success_response(
        data=bank_account_service.set_default_bank_account(
            bank_account_id, current_user.id
        )
    )


@router.delete(
    "/{bank_account_id}",
    response_model=APIResponse[None],
    responses={
        400: {"model": BadRequestResponse},
        404: {"model": NotFoundResponse},
    },
)
@limiter.limit("10/minute")
async def remove_bank_account(
    request: Request,
    bank_account_id: str,
    current_user: ActiveUserDep,
    bank_account_service: BankAccountServiceDep,
):
    """Remove a payout account.

    Soft delete — ledger rows and past payouts still reference it. Refused
    while a withdrawal to it is in flight.
    """
    bank_account_service.remove_bank_account(bank_account_id, current_user.id)
    return success_response(message="Bank account removed")
