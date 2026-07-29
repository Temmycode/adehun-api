"""Client-facing idempotency for money-moving routes.

USAGE — the router drives it in three lines:

    @router.post("/withdraw", ...)
    async def withdraw(request: Request, payload: WithdrawalCreate,
                       current_user: ActiveUserDep,
                       wallet_service: WalletServiceDep,
                       idem: IdempotencyDep):
        replay = idem.begin("POST /wallet/withdraw", payload)
        if replay is not None:
            return replay
        result = await wallet_service.request_withdrawal(current_user.id, payload)
        return idem.complete(success_response(data=result, status_code=202))

WHY AN EXPLICIT CONTEXT AND NOT MIDDLEWARE
ASGI middleware cannot see the authenticated user without re-running auth, has
to buffer every response body globally, and would apply to reads as well. This
is money code — it should be obvious at the call site, not clever.

WHAT THIS DOES AND DOES NOT GUARANTEE
This layer is a UX convenience: it lets a client safely retry a request that
timed out and receive the original response. The durable money-safety guarantee
is the UNIQUE index on `transaction.reference`. If a key is swept early or the
client omits the header entirely, the ledger still refuses to double-spend.

SESSION SHARING
This runs on the request's shared session, like every other repository. Each of
`reserve`, `complete` and `release` commits on its own, and the reservation is
committed before any money work starts — so a rollback inside `apply_entry`
discards the money operation without losing the reservation, and the teardown
below then releases it so the client can retry with the same key.
"""

import hashlib
import json
from typing import Any

from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.common.enums import IdempotencyStatus
from app.exceptions import (
    BadRequestError,
    IdempotencyConflictError,
    IdempotencyKeyReusedError,
)
from app.logging import get_logger
from app.repository.idempotency_repository import IdempotencyRepository

logger = get_logger(__name__)

_MAX_KEY_LENGTH = 120


def _canonical_hash(payload: BaseModel | dict[str, Any] | None) -> str:
    """Stable sha256 of a request body, so a retry with different content is caught."""
    if payload is None:
        body: Any = {}
    elif isinstance(payload, BaseModel):
        body = payload.model_dump(mode="json")
    else:
        body = payload
    encoded = json.dumps(body, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


class IdempotencyContext:
    """Reserve, then either replay a stored response or record a new one."""

    def __init__(
        self,
        repository: IdempotencyRepository,
        user_id: str,
        key: str | None,
    ):
        self._repository = repository
        self._user_id = user_id
        self._key = key
        self._record_id: str | None = None
        self._completed = False

    @property
    def key_supplied(self) -> bool:
        return bool(self._key)

    def begin(
        self,
        endpoint: str,
        payload: BaseModel | dict[str, Any] | None = None,
        *,
        required: bool = True,
    ) -> JSONResponse | None:
        """Claim the key.

        Returns a replay response to return verbatim, or None to proceed with
        the operation.
        """
        if not self._key:
            if required:
                raise BadRequestError("Idempotency-Key header is required")
            return None

        if len(self._key) > _MAX_KEY_LENGTH:
            raise BadRequestError(
                f"Idempotency-Key must be at most {_MAX_KEY_LENGTH} characters"
            )

        request_hash = _canonical_hash(payload)

        record_id = self._repository.reserve(
            user_id=self._user_id,
            endpoint=endpoint,
            key=self._key,
            request_hash=request_hash,
        )
        if record_id is not None:
            self._record_id = record_id
            return None

        # Someone else holds the reservation. Work out which case this is.
        existing = self._repository.get(
            user_id=self._user_id, endpoint=endpoint, key=self._key
        )
        if existing is None:
            # Raced with a sweep between the insert and the read; let the caller
            # proceed — the ledger reference still protects the money.
            logger.warning(
                "idempotency reservation vanished, proceeding unguarded",
                extra={"endpoint": endpoint, "user_id": self._user_id},
            )
            return None

        if existing.request_hash != request_hash:
            raise IdempotencyKeyReusedError()

        if existing.status == IdempotencyStatus.COMPLETED:
            logger.info(
                "replaying idempotent response",
                extra={"endpoint": endpoint, "user_id": self._user_id},
            )
            return JSONResponse(
                status_code=existing.response_status_code or 200,
                content=existing.response_body,
                headers={"Idempotent-Replay": "true"},
            )

        # Still in flight. 409 rather than block: waiting would pin a connection
        # from a small synchronous pool for the length of an outbound Paystack
        # call, and there is nowhere to park the request.
        raise IdempotencyConflictError()

    def bind_reference(self, reference: str) -> None:
        """Link the key to the ledger entry it produced, for support lookups."""
        if self._record_id is None:
            return
        try:
            self._repository.bind_reference(self._record_id, reference)
        except Exception:
            logger.warning(
                "failed to bind idempotency reference",
                extra={"reference": reference},
                exc_info=True,
            )

    def complete(self, response: JSONResponse) -> JSONResponse:
        """Store the response for replay and return it unchanged."""
        if self._record_id is None:
            return response

        try:
            body = json.loads(response.body)
        except Exception:
            body = None

        self._repository.complete(
            self._record_id, status_code=response.status_code, body=body
        )
        self._completed = True
        return response

    def release_if_abandoned(self) -> None:
        """Teardown: drop the reservation if the handler raised.

        Without this, a failed request would block the client from retrying with
        the same key until the in-flight timeout elapsed.
        """
        if self._record_id is None or self._completed:
            return
        try:
            self._repository.release(self._record_id)
        except Exception:
            logger.warning(
                "failed to release abandoned idempotency reservation",
                extra={"record_id": self._record_id},
                exc_info=True,
            )
