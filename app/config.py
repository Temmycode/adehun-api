import os
from decimal import Decimal
from pathlib import Path
from typing import Literal

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

Environment = Literal["development", "test", "production"]

# Which dotenv file backs each environment. Real deployments should inject
# process env vars and ship no file at all; the file is a local convenience.
_ENV_FILES: dict[str, tuple[str, ...]] = {
    "development": (".env.local", ".env.development"),
    "test": (".env.test",),
    "production": (".env.production",),
}


def _current_environment() -> str:
    value = os.environ.get("ENVIRONMENT", "development").strip().lower()
    return value if value in _ENV_FILES else "development"


def _resolve_env_file() -> str | None:
    for candidate in _ENV_FILES[_current_environment()]:
        if Path(candidate).is_file():
            return candidate
    return None


class Settings(BaseSettings):
    """Runtime configuration, read from process env and (optionally) a dotenv file.

    Secrets never have defaults: a missing value fails at import, which is the
    behaviour we want in production.
    """

    environment: Environment = "development"
    debug: bool = False

    database_hostname: str
    database_port: str
    database_password: str
    database_name: str
    database_username: str
    # "prefer" keeps local Postgres working; production must set "require".
    database_sslmode: str = "prefer"

    # JWT. The algorithm is pinned in token_service, never read from env.
    secret_key: str
    access_token_expiration_minutes: int = 30
    refresh_token_expiration_days: int = 3

    cloudinary_cloud_name: str
    cloudinary_api_key: str
    cloudinary_secret_key: str
    cloudinary_max_file_bytes: int = 25 * 1024 * 1024

    redis_database_host: str
    redis_database_password: str
    redis_database_port: str

    resend_api_key: str | None = None
    # Sender for transactional email. MUST be on a domain verified in Resend —
    # the default only works in Resend's sandbox, which delivers solely to your
    # own account address. "Adehun <invites@yourdomain.com>" is also valid.
    resend_from_email: str = "onboarding@resend.dev"

    # Public origin of this API. Invitation emails link to {web_url}/invite.
    web_url: str

    # Comma-separated browser origins allowed to call the API with credentials.
    # Empty means "no browser origins" — the mobile app does not need CORS.
    cors_origins: list[str] = []
    # Set true only behind a trusted reverse proxy (Render, nginx) so the rate
    # limiter keys on the real client IP from X-Forwarded-For.
    trust_proxy_headers: bool = False
    sentry_dsn: str | None = None

    firebase_service_account_json: str

    # SHA-256 fingerprint(s) of the Android signing certificate, for
    # /.well-known/assetlinks.json. Comma-separated, colon-delimited hex.
    android_cert_sha256: list[str] = []
    android_package_name: str = "com.tolutech.adehun.adehun_mvp"
    ios_app_store_url: str | None = None
    android_play_store_url: str | None = None

    # ------------------------------------------------------------------ #
    #  Payments                                                          #
    # ------------------------------------------------------------------ #
    paystack_base_url: str = "https://api.paystack.co"
    paystack_test_public_key: str
    paystack_test_secret_key: str
    paystack_live_mode: bool = False
    paystack_secret_key: str | None = None  # live
    paystack_public_key: str | None = None  # live
    paystack_callback_url: str | None = None
    paystack_transfers_enabled: bool = False  # kill switch for payouts

    withdrawal_min_amount: Decimal = Decimal("100.00")
    withdrawal_max_amount: Decimal = Decimal("1000000.00")
    wallet_fund_max_amount: Decimal = Decimal("10000000.00")
    agreement_max_amount: Decimal = Decimal("50000000.00")

    idempotency_ttl_hours: int = 24
    idempotency_inflight_timeout_seconds: int = 120

    model_config = SettingsConfigDict(env_file=_resolve_env_file(), extra="ignore")

    @field_validator("environment", mode="before")
    @classmethod
    def _default_environment(cls, value: str | None) -> str:
        return (value or _current_environment()).strip().lower()

    @field_validator("secret_key")
    @classmethod
    def _strong_secret(cls, value: str) -> str:
        value = value.strip()
        if len(value) < 32:
            raise ValueError("SECRET_KEY must be at least 32 characters")
        if value.lower() in {"secret", "changeme", "change-me", "password"}:
            raise ValueError("SECRET_KEY is a placeholder value")
        return value

    @field_validator("cors_origins", "android_cert_sha256", mode="before")
    @classmethod
    def _split_csv(cls, value: object) -> object:
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return value

    @property
    def is_production(self) -> bool:
        return self.environment == "production"

    @property
    def paystack_active_secret_key(self) -> str:
        """The secret key outbound API calls should authenticate with."""
        if self.paystack_live_mode:
            if not self.paystack_secret_key:
                raise RuntimeError(
                    "paystack_live_mode is True but paystack_secret_key is unset"
                )
            return self.paystack_secret_key
        return self.paystack_test_secret_key

    @property
    def paystack_active_public_key(self) -> str:
        if self.paystack_live_mode and self.paystack_public_key:
            return self.paystack_public_key
        return self.paystack_test_public_key

    @property
    def paystack_webhook_secret(self) -> str:
        """The ONLY key a webhook signature is checked against.

        Accepting the test key in live mode would let anyone holding the test
        secret forge a `charge.success` and mint real balance.
        """
        return self.paystack_active_secret_key


settings = Settings()  # pyright: ignore[reportCallIssue]

if settings.is_production and settings.debug:
    raise RuntimeError("DEBUG must be false when ENVIRONMENT=production")
