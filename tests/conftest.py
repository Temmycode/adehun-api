"""Test harness.

* Real Postgres (`adehun_test` on the local server) migrated with Alembic, so
  every constraint, index and `SELECT … FOR UPDATE` behaves as in production.
* Tables are truncated after each test. Repositories commit freely, so a
  savepoint-per-test strategy would be fighting the code under test.
* No Redis (every repository tolerates `None`), no network: Paystack, Firebase
  and Resend are replaced with in-process fakes.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import uuid
from collections.abc import Callable
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

# --- environment must be set before `app` is imported ---------------------
os.environ.update(
    {
        "ENVIRONMENT": "test",
        "DEBUG": "false",
        "DATABASE_HOSTNAME": os.environ.get("TEST_DATABASE_HOSTNAME", "/tmp"),
        "DATABASE_PORT": os.environ.get("TEST_DATABASE_PORT", "5432"),
        "DATABASE_USERNAME": os.environ.get(
            "TEST_DATABASE_USERNAME", os.environ.get("USER", "postgres")
        ),
        "DATABASE_PASSWORD": os.environ.get("TEST_DATABASE_PASSWORD", "postgres"),
        "DATABASE_NAME": os.environ.get("TEST_DATABASE_NAME", "adehun_test"),
        "SECRET_KEY": "test-secret-key-that-is-long-enough-for-validation-0123456789",
        "CLOUDINARY_CLOUD_NAME": "testcloud",
        "CLOUDINARY_API_KEY": "cloud-key",
        "CLOUDINARY_SECRET_KEY": "cloud-secret",
        "REDIS_DATABASE_HOST": "localhost",
        "REDIS_DATABASE_PASSWORD": "",
        "REDIS_DATABASE_PORT": "6379",
        "WEB_URL": "http://testserver",
        "FIREBASE_SERVICE_ACCOUNT_JSON": "{}",
        "PAYSTACK_TEST_PUBLIC_KEY": "pk_test_x",
        "PAYSTACK_TEST_SECRET_KEY": "sk_test_webhook_secret",
        "PAYSTACK_TRANSFERS_ENABLED": "false",
        "LOG_LEVEL": "WARNING",
    }
)

import psycopg2
import pytest
from alembic import command
from alembic.config import Config
from app.common.enums import LedgerEntryType
from app.config import settings
from app.database import engine
from app.main import app
from app.models import User
from app.rate_limiting import limiter
from app.redis import get_redis_dep
from app.repository.wallet_repository import WalletRepository
from app.service import token_service
from app.service.paystack_client import PaystackError
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlmodel import Session, SQLModel

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# ---------------------------------------------------------------------------
# Database lifecycle
# ---------------------------------------------------------------------------


def _admin_connection():
    host = settings.database_hostname
    kwargs: dict[str, Any] = {
        "dbname": "postgres",
        "user": settings.database_username,
        "password": settings.database_password,
        "port": int(settings.database_port),
    }
    kwargs["host"] = host
    conn = psycopg2.connect(**kwargs)
    conn.autocommit = True
    return conn


@pytest.fixture(scope="session", autouse=True)
def _database():
    """Recreate the test database and migrate it to head once per run."""
    conn = _admin_connection()
    with conn.cursor() as cur:
        cur.execute(f'DROP DATABASE IF EXISTS "{settings.database_name}" WITH (FORCE)')
        cur.execute(f'CREATE DATABASE "{settings.database_name}"')
    conn.close()

    cfg = Config(os.path.join(ROOT, "alembic.ini"))
    cfg.set_main_option("script_location", os.path.join(ROOT, "alembic"))
    command.upgrade(cfg, "head")
    yield
    engine.dispose()


@pytest.fixture(autouse=True)
def _clean_tables():
    """Truncate every application table after each test."""
    yield
    tables = [t.name for t in SQLModel.metadata.sorted_tables]
    with engine.begin() as conn:
        conn.execute(
            text(
                "TRUNCATE TABLE "
                + ", ".join(f'"{name}"' for name in tables)
                + " RESTART IDENTITY CASCADE"
            )
        )


@pytest.fixture(autouse=True)
def _no_rate_limits():
    limiter.enabled = False
    yield
    limiter.enabled = True


@pytest.fixture(autouse=True)
def _no_redis():
    app.dependency_overrides[get_redis_dep] = lambda: None
    yield
    app.dependency_overrides.pop(get_redis_dep, None)


@pytest.fixture
def session():
    with Session(engine) as s:
        yield s


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class FakePaystackClient:
    """Programmable stand-in for `PaystackClient`. Records every call."""

    def __init__(self):
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.verify_result: dict[str, Any] | Callable[[str], dict[str, Any]] = {}
        self.verify_error: Exception | None = None
        self.transfer_verify_result: dict[str, Any] = {"status": "success"}
        self.initialize_error: Exception | None = None
        self.transfer_error: Exception | None = None
        self.banks = [
            {"name": "Test Bank", "code": "001", "currency": "NGN", "type": "nuban"},
            {"name": "Other Bank", "code": "002", "currency": "NGN", "type": "nuban"},
        ]
        self.resolved_name = "ADA LOVELACE"

    async def aclose(self):
        pass

    async def initialize_transaction(self, **kwargs):
        self.calls.append(("initialize_transaction", kwargs))
        if self.initialize_error:
            raise self.initialize_error
        return {
            "access_code": "ac_test",
            "authorization_url": "https://checkout.paystack.test/x",
            "reference": kwargs["reference"],
        }

    async def verify_transaction(self, reference: str):
        self.calls.append(("verify_transaction", {"reference": reference}))
        if self.verify_error:
            raise self.verify_error
        if callable(self.verify_result):
            return self.verify_result(reference)
        return self.verify_result

    async def list_banks(self, **kwargs):
        self.calls.append(("list_banks", kwargs))
        return self.banks

    async def resolve_account_number(self, **kwargs):
        self.calls.append(("resolve_account_number", kwargs))
        return {
            "account_number": kwargs["account_number"],
            "account_name": self.resolved_name,
        }

    async def create_transfer_recipient(self, **kwargs):
        self.calls.append(("create_transfer_recipient", kwargs))
        return {"recipient_code": "RCP_test"}

    async def initiate_transfer(self, **kwargs):
        self.calls.append(("initiate_transfer", kwargs))
        if self.transfer_error:
            raise self.transfer_error
        return {"transfer_code": "TRF_test", "id": 991}

    async def verify_transfer(self, reference: str):
        self.calls.append(("verify_transfer", {"reference": reference}))
        return self.transfer_verify_result


@pytest.fixture
def paystack(monkeypatch) -> FakePaystackClient:
    fake = FakePaystackClient()
    monkeypatch.setattr("app.service.paystack_client.paystack_client", fake)
    monkeypatch.setattr("app.service.wallet_service.paystack_client", fake)
    monkeypatch.setattr("app.service.bank_account_service.paystack_client", fake)
    return fake


@pytest.fixture
def firebase(monkeypatch):
    """Firebase Admin stub: `register(uid, email, name)` then sign in with uid."""
    users: dict[str, SimpleNamespace] = {}

    def register(uid: str, email: str, name: str = "New User") -> str:
        users[uid] = SimpleNamespace(
            uid=uid, email=email, display_name=name, photo_url=None
        )
        return f"idtoken:{uid}"

    def verify_id_token(token: str):
        prefix, _, uid = token.partition(":")
        if prefix != "idtoken" or uid not in users:
            raise ValueError("bad token")
        return {"uid": uid}

    def get_user(uid: str):
        return users[uid]

    monkeypatch.setattr(
        "app.service.auth_service.auth.verify_id_token", verify_id_token
    )
    monkeypatch.setattr("app.service.auth_service.auth.get_user", get_user)
    return SimpleNamespace(register=register, users=users)


# ---------------------------------------------------------------------------
# Factories
# ---------------------------------------------------------------------------


@pytest.fixture
def make_user(session):
    def _make(
        email: str | None = None,
        name: str = "Test User",
        *,
        active: bool = True,
        is_admin: bool = False,
        phone: str | None = "+2348012345678",
    ) -> User:
        user = User(
            id=str(uuid.uuid4()),
            email=email or f"{uuid.uuid4().hex[:8]}@example.com",
            name=name,
            phone_number=phone,
            active=1 if active else 0,
            is_admin=is_admin,
        )
        session.add(user)
        session.commit()
        session.refresh(user)
        return user

    return _make


def bearer(user: User) -> dict[str, str]:
    return {"Authorization": f"Bearer {token_service.create_token(user.id, 'access')}"}


@pytest.fixture
def auth_headers():
    return bearer


@pytest.fixture
def credit_wallet(session):
    def _credit(user: User, amount: str | Decimal) -> None:
        repo = WalletRepository(session, None)
        repo.apply_entry(
            user_id=user.id,
            entry_type=LedgerEntryType.DEPOSIT,
            amount=Decimal(str(amount)),
            reference=f"test_dep_{uuid.uuid4().hex}",
            description="test credit",
        )

    return _credit


@pytest.fixture
def make_agreement(client):
    """Create an agreement through the API as `depositor`, inviting `invitee`."""

    def _make(
        depositor: User,
        invitee: User,
        *,
        amount: str = "1000.00",
        role: str = "depositor",
        conditions: list[dict] | None = None,
        title: str = "Build a website",
    ) -> dict:
        if conditions is None:
            conditions = [
                {
                    "title": "Deliver design",
                    "description": "Figma file delivered",
                    "required_from_email": invitee.email,
                }
            ]
        resp = client.post(
            "/agreements/",
            json={
                "other_participant_email_or_phone": invitee.email,
                "role": role,
                "title": title,
                "description": "A test agreement",
                "amount": amount,
                "conditions": conditions,
            },
            headers=bearer(depositor),
        )
        assert resp.status_code == 201, resp.text
        return resp.json()["data"]

    return _make


@pytest.fixture
def accept_as(client):
    def _accept(user: User, agreement_id: str) -> dict:
        resp = client.post(
            f"/agreements/{agreement_id}/accept",
            headers={**bearer(user), "Idempotency-Key": str(uuid.uuid4())},
        )
        assert resp.status_code == 200, resp.text
        return resp.json()["data"]

    return _accept


@pytest.fixture
def fund_as(client):
    def _fund(user: User, agreement_id: str, key: str | None = None):
        return client.post(
            f"/agreements/{agreement_id}/fund",
            headers={**bearer(user), "Idempotency-Key": key or str(uuid.uuid4())},
        )

    return _fund


def sign_webhook(body: bytes, secret: str | None = None) -> str:
    key = (secret or settings.paystack_webhook_secret).encode()
    return hmac.new(key, body, hashlib.sha512).hexdigest()


@pytest.fixture
def post_webhook(client):
    def _post(payload: dict, secret: str | None = None):
        body = json.dumps(payload).encode()
        return client.post(
            "/wallet/webhook/paystack",
            content=body,
            headers={
                "content-type": "application/json",
                "x-paystack-signature": sign_webhook(body, secret),
            },
        )

    return _post


@pytest.fixture
def paystack_error():
    return PaystackError
