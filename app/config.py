from decimal import Decimal

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Access to our env file data"""

    database_hostname: str
    database_port: str
    database_password: str
    database_name: str
    database_username: str
    secret_key: str
    algorithm: str
    access_token_expiration_minutes: int
    refresh_token_expiration_days: int
    cloudinary_cloud_name: str
    cloudinary_api_key: str
    cloudinary_secret_key: str
    redis_database_host: str
    redis_database_password: str
    redis_database_port: str
    resend_api_key: str | None = None
    web_url: str
    debug: bool = True
    paystack_test_public_key: str
    paystack_test_secret_key: str
    firebase_service_account_json: str

    # ------------------------------------------------------------------ #
    #  Payments                                                          #
    #                                                                    #
    #  Every field below needs a default: `env_file` is pinned to        #
    #  .env.production, which does not carry them.                       #
    # ------------------------------------------------------------------ #
    paystack_base_url: str = "https://api.paystack.co"
    paystack_live_mode: bool = False
    paystack_secret_key: str | None = None  # live
    paystack_public_key: str | None = None  # live
    paystack_callback_url: str | None = None
    paystack_transfers_enabled: bool = False  # kill switch for payouts

    withdrawal_min_amount: Decimal = Decimal("100.00")
    withdrawal_max_amount: Decimal = Decimal("1000000.00")

    idempotency_ttl_hours: int = 24
    idempotency_inflight_timeout_seconds: int = 120

    model_config = {
        "env_file": ".env.production",
    }

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
    def paystack_webhook_secrets(self) -> tuple[str, ...]:
        """Every key a webhook signature may have been generated with.

        Both are tried so test-mode and live-mode webhooks verify side by side.
        """
        return tuple(
            key
            for key in (self.paystack_test_secret_key, self.paystack_secret_key)
            if key
        )


settings = Settings()  # pyright: ignore[reportCallIssue]
