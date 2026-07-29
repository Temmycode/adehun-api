"""The user's financial history.

This lives at `/transactions` rather than `/wallet/transactions` because the
ledger spans wallet funding, agreement escrow movements and bank payouts — it
is the user's financial history, not a sub-resource of the balance object.
"""

from datetime import datetime
from decimal import Decimal

from fastapi import APIRouter, Query, Request

from app.common.enums import LedgerDirection, LedgerEntryStatus, LedgerEntryType
from app.core.response import (
    APIResponse,
    InternalServerErrorResponse,
    NotFoundResponse,
    UnauthorizedResponse,
    success_response,
)
from app.dependencies import ActiveUserDep, TransactionServiceDep
from app.rate_limiting import limiter
from app.schemas.transactions_schema import (
    TransactionListResponse,
    TransactionResponse,
    TransactionSummaryResponse,
)

router = APIRouter(
    prefix="/transactions",
    tags=["Transactions"],
    responses={
        401: {"model": UnauthorizedResponse},
        500: {"model": InternalServerErrorResponse},
    },
)


@router.get("", response_model=APIResponse[TransactionListResponse])
@limiter.limit("60/minute")
async def get_transactions(
    request: Request,
    current_user: ActiveUserDep,
    transaction_service: TransactionServiceDep,
    skip: int = 0,
    limit: int = Query(20, ge=1, le=100),
    type: list[LedgerEntryType] | None = Query(
        None, description="Repeatable, e.g. ?type=deposit&type=withdrawal"
    ),
    direction: LedgerDirection | None = None,
    status: LedgerEntryStatus | None = None,
    agreement_id: str | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    min_amount: Decimal | None = None,
    max_amount: Decimal | None = None,
    search: str | None = Query(None, description="Matches description or reference"),
):
    """Every money movement for the authenticated user.

    Deposits, escrow locks and releases, withdrawals and reversals in a single
    stream, newest first.
    """
    return success_response(
        data=transaction_service.get_user_transactions(
            current_user.id,
            skip=skip,
            limit=limit,
            types=type,
            direction=direction,
            status=status,
            agreement_id=agreement_id,
            date_from=date_from,
            date_to=date_to,
            min_amount=min_amount,
            max_amount=max_amount,
            search=search,
        )
    )


@router.get("/summary", response_model=APIResponse[TransactionSummaryResponse])
@limiter.limit("30/minute")
async def get_transaction_summary(
    request: Request,
    current_user: ActiveUserDep,
    transaction_service: TransactionServiceDep,
):
    """Lifetime totals in and out for the authenticated user."""
    return success_response(data=transaction_service.get_summary(current_user.id))


@router.get(
    "/{transaction_id}",
    response_model=APIResponse[TransactionResponse],
    responses={404: {"model": NotFoundResponse}},
)
@limiter.limit("60/minute")
async def get_transaction(
    request: Request,
    transaction_id: str,
    current_user: ActiveUserDep,
    transaction_service: TransactionServiceDep,
):
    """Get one transaction. Scoped to the authenticated user."""
    return success_response(
        data=transaction_service.get_transaction(transaction_id, current_user.id)
    )
