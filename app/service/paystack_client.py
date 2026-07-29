"""Thin async wrapper around the Paystack REST API.

Every outbound call to Paystack goes through here. Nothing else in the codebase
should build a Paystack URL or an Authorization header.

RETRY POLICY — the important part:
  - Reads (`verify_*`, `list_banks`, `resolve_account_number`) retry, because
    they are safe to repeat.
  - `initiate_transfer` NEVER retries. A retried transfer POST can pay twice.
    On a timeout the outcome is genuinely unknown, so it raises
    `PaystackTimeoutError` and the caller must leave its record PENDING for the
    webhook (or a later `verify_transfer`) to reconcile — it must NOT reverse
    the debit.
"""

import asyncio
from typing import Any

import httpx

from app.config import settings
from app.exceptions import AppError
from app.logging import get_logger

logger = get_logger(__name__)

_TIMEOUT = httpx.Timeout(connect=5.0, read=30.0, write=10.0, pool=5.0)
_LIMITS = httpx.Limits(max_connections=20, max_keepalive_connections=10)
_RETRY_BACKOFF_SECONDS = (0.5, 1.5)

# Paystack surfaces input problems as HTTP 200 with `status: false`, so the
# message has to be sniffed to tell "you sent rubbish" from "we broke".
_VALIDATION_HINTS = (
    "could not resolve",
    "cannot resolve",
    "invalid",
    "not found",
    "unknown bank",
    "no such",
    "is required",
    "must be",
)


class PaystackError(AppError):
    """Paystack could not fulfil the request."""

    def __init__(
        self,
        message: str = "Payment provider error",
        *,
        status_code: int = 502,
        code: str = "PAYSTACK_ERROR",
        provider_code: str | None = None,
    ):
        super().__init__(message=message, code=code, status_code=status_code)
        self.provider_code = provider_code


class PaystackTimeoutError(PaystackError):
    """The outcome is UNKNOWN. Callers must NOT reverse a debit on this."""

    def __init__(self, message: str = "Payment provider timed out"):
        super().__init__(message, status_code=504, code="PAYSTACK_TIMEOUT")


class PaystackValidationError(PaystackError):
    """Paystack rejected the input (bad account number, invalid bank code)."""

    def __init__(self, message: str = "Payment provider rejected the request"):
        super().__init__(
            message, status_code=400, code="PAYSTACK_VALIDATION_ERROR"
        )


class PaystackDuplicateReferenceError(PaystackError):
    """This reference was already used. The original request went through."""

    def __init__(self, message: str = "This reference has already been used"):
        super().__init__(
            message, status_code=409, code="PAYSTACK_DUPLICATE_REFERENCE"
        )


def _looks_like_validation(message: str) -> bool:
    lowered = message.lower()
    return any(hint in lowered for hint in _VALIDATION_HINTS)


def _looks_like_duplicate_reference(message: str) -> bool:
    lowered = message.lower()
    return "reference" in lowered and (
        "duplicate" in lowered or "already" in lowered or "has been used" in lowered
    )


class PaystackClient:
    """A single long-lived httpx client, so connections are pooled."""

    def __init__(self, secret_key: str, base_url: str):
        self._secret_key = secret_key
        self._base_url = base_url.rstrip("/")
        self._client: httpx.AsyncClient | None = None

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                base_url=self._base_url,
                timeout=_TIMEOUT,
                limits=_LIMITS,
                headers={
                    "Authorization": f"Bearer {self._secret_key}",
                    "Content-Type": "application/json",
                },
            )
        return self._client

    async def aclose(self) -> None:
        """Close the pooled client. Called from the app lifespan teardown."""
        if self._client is not None and not self._client.is_closed:
            await self._client.aclose()
        self._client = None

    # ------------------------------------------------------------------ #
    #  Transport                                                         #
    # ------------------------------------------------------------------ #

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
        retries: int = 0,
        reference: str | None = None,
    ) -> dict[str, Any]:
        """Perform a request and return the `data` payload.

        Raises a `PaystackError` subclass on any failure. Never logs the key.
        """
        client = self._get_client()
        attempts = retries + 1
        last_error: Exception | None = None

        for attempt in range(attempts):
            try:
                response = await client.request(
                    method, path, json=json, params=params
                )
            except (httpx.TimeoutException, httpx.ConnectError) as err:
                last_error = err
                logger.warning(
                    "paystack request timed out",
                    extra={
                        "method": method,
                        "path": path,
                        "attempt": attempt + 1,
                        "reference": reference,
                    },
                )
                if attempt + 1 < attempts:
                    await asyncio.sleep(_RETRY_BACKOFF_SECONDS[attempt])
                    continue
                raise PaystackTimeoutError() from err
            except httpx.RequestError as err:
                logger.exception(
                    "paystack request failed",
                    extra={"method": method, "path": path, "reference": reference},
                )
                raise PaystackError("Could not reach the payment provider") from err

            if response.status_code >= 500:
                last_error = PaystackError(
                    f"Payment provider returned {response.status_code}"
                )
                logger.warning(
                    "paystack returned a server error",
                    extra={
                        "method": method,
                        "path": path,
                        "http_status": response.status_code,
                        "attempt": attempt + 1,
                        "reference": reference,
                    },
                )
                if attempt + 1 < attempts:
                    await asyncio.sleep(_RETRY_BACKOFF_SECONDS[attempt])
                    continue
                raise last_error

            return self._parse(response, method=method, path=path, reference=reference)

        # Unreachable: the loop either returns or raises.
        raise PaystackError("Payment provider request failed") from last_error

    def _parse(
        self,
        response: httpx.Response,
        *,
        method: str,
        path: str,
        reference: str | None,
    ) -> dict[str, Any]:
        try:
            body = response.json()
        except ValueError as err:
            logger.error(
                "paystack returned a non-JSON body",
                extra={
                    "method": method,
                    "path": path,
                    "http_status": response.status_code,
                    "body_preview": response.text[:500],
                    "reference": reference,
                },
            )
            raise PaystackError(
                "Unexpected response from the payment provider"
            ) from err

        message = str(body.get("message") or "")

        if not body.get("status"):
            logger.warning(
                "paystack rejected the request",
                extra={
                    "method": method,
                    "path": path,
                    "http_status": response.status_code,
                    "provider_message": message,
                    "reference": reference,
                },
            )
            if _looks_like_duplicate_reference(message):
                raise PaystackDuplicateReferenceError(
                    message or "This reference has already been used"
                )
            if response.status_code < 500 and _looks_like_validation(message):
                raise PaystackValidationError(message or "Request was rejected")
            raise PaystackError(
                message or "Payment provider error",
                provider_code=body.get("code"),
            )

        data = body.get("data")
        if data is None:
            raise PaystackError("Payment provider returned no data")
        return data

    # ------------------------------------------------------------------ #
    #  Charges                                                           #
    # ------------------------------------------------------------------ #

    async def initialize_transaction(
        self,
        *,
        email: str,
        amount_kobo: int,
        reference: str,
        channels: list[str] | None = None,
        callback_url: str | None = None,
    ) -> dict[str, Any]:
        """Start a payment. Returns access_code / authorization_url / reference."""
        payload: dict[str, Any] = {
            "email": email,
            "amount": amount_kobo,
            "reference": reference,
        }
        if channels:
            payload["channels"] = channels
        if callback_url:
            payload["callback_url"] = callback_url

        return await self._request(
            "POST", "/transaction/initialize", json=payload, reference=reference
        )

    async def verify_transaction(self, reference: str) -> dict[str, Any]:
        """Server-side truth for a charge. Safe to retry."""
        return await self._request(
            "GET", f"/transaction/verify/{reference}", retries=2, reference=reference
        )

    # ------------------------------------------------------------------ #
    #  Banks and recipients                                              #
    # ------------------------------------------------------------------ #

    async def list_banks(
        self, *, country: str = "nigeria", currency: str = "NGN"
    ) -> list[dict[str, Any]]:
        """The bank list. Large and near-static — cache the result."""
        data = await self._request(
            "GET",
            "/bank",
            params={"country": country, "currency": currency, "perPage": 100},
            retries=2,
        )
        return data if isinstance(data, list) else []

    async def resolve_account_number(
        self, *, account_number: str, bank_code: str
    ) -> dict[str, Any]:
        """Look up the real account holder. Billed per call in live mode."""
        return await self._request(
            "GET",
            "/bank/resolve",
            params={"account_number": account_number, "bank_code": bank_code},
            retries=2,
        )

    async def create_transfer_recipient(
        self,
        *,
        name: str,
        account_number: str,
        bank_code: str,
        currency: str = "NGN",
    ) -> dict[str, Any]:
        """Register a payout destination. Returns the recipient_code."""
        return await self._request(
            "POST",
            "/transferrecipient",
            json={
                "type": "nuban",
                "name": name,
                "account_number": account_number,
                "bank_code": bank_code,
                "currency": currency,
            },
        )

    # ------------------------------------------------------------------ #
    #  Transfers                                                         #
    # ------------------------------------------------------------------ #

    async def initiate_transfer(
        self,
        *,
        amount_kobo: int,
        recipient_code: str,
        reference: str,
        reason: str,
    ) -> dict[str, Any]:
        """Send money out.

        `retries=0` is deliberate and must stay that way: a retried transfer
        POST can pay the same person twice.
        """
        return await self._request(
            "POST",
            "/transfer",
            json={
                "source": "balance",
                "amount": amount_kobo,
                "recipient": recipient_code,
                "reference": reference,
                "reason": reason,
            },
            retries=0,
            reference=reference,
        )

    async def verify_transfer(self, reference: str) -> dict[str, Any]:
        """Server-side truth for a transfer. Safe to retry."""
        return await self._request(
            "GET", f"/transfer/verify/{reference}", retries=2, reference=reference
        )


paystack_client = PaystackClient(
    secret_key=settings.paystack_active_secret_key,
    base_url=settings.paystack_base_url,
)
