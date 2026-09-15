from datetime import datetime, timedelta, timezone
from typing import Annotated, Literal
from uuid import uuid4

import jwt
from fastapi import Depends, HTTPException, WebSocket
from fastapi.security import OAuth2PasswordBearer
from sqlmodel import Session

from app.config import settings
from app.database import SessionDep
from app.exceptions import AdminAccessRequiredError
from app.logging import get_logger
from app.models import User

logger = get_logger(__name__)
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="auth/login")

SECRET_KEY = settings.secret_key
# Pinned in code. Reading the algorithm from the environment let a bad env
# edit ("none", "RS256") turn every token into a forgery.
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRATION_MINUTES = settings.access_token_expiration_minutes
REFRESH_TOKEN_EXPIRATION_DAYS = settings.refresh_token_expiration_days

TokenType = Literal["access", "refresh"]

_REQUIRED_CLAIMS = ["sub", "type", "exp", "iat", "jti"]


def _credentials_exception() -> HTTPException:
    return HTTPException(
        status_code=401,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )


# ------------------------------------------------------------------
# Token Creation
# ------------------------------------------------------------------


def token_lifetime(token_type: TokenType) -> timedelta:
    if token_type == "access":
        return timedelta(minutes=ACCESS_TOKEN_EXPIRATION_MINUTES)
    return timedelta(days=REFRESH_TOKEN_EXPIRATION_DAYS)


def create_token(
    user_id: str,
    token_type: TokenType,
    expires_delta: timedelta | None = None,
    extra_claims: dict | None = None,
    jti: str | None = None,
) -> str:
    """Mint a signed JWT.

    Every token carries `jti` (so refresh tokens can be individually revoked)
    and `iat`. `jti` may be supplied so the caller can persist it first.
    """
    now = datetime.now(timezone.utc)
    expire = now + (expires_delta or token_lifetime(token_type))

    payload: dict = {
        "sub": user_id,
        "type": token_type,
        "iat": now,
        "exp": expire,
        "jti": jti or uuid4().hex,
    }
    if extra_claims:
        payload.update(extra_claims)

    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


# ------------------------------------------------------------------
# Token Verification
# ------------------------------------------------------------------


def verify_token(token: str, expected_type: TokenType) -> dict:
    """Validate signature, expiry, required claims and token type."""
    try:
        payload = jwt.decode(
            token,
            SECRET_KEY,
            algorithms=[ALGORITHM],
            options={"require": _REQUIRED_CLAIMS},
        )
    except jwt.PyJWTError as exc:
        raise _credentials_exception() from exc

    if payload.get("type") != expected_type or not payload.get("sub"):
        raise _credentials_exception()

    return payload


def _load_user(session: Session, user_id: str) -> User:
    """Resolve the token subject; inactive accounts are rejected everywhere."""
    user = session.get(User, user_id)
    if not user or user.active == 0:
        raise _credentials_exception()
    return user


# ------------------------------------------------------------------
# FastAPI dependencies
# ------------------------------------------------------------------


def get_current_user(
    token: Annotated[str, Depends(oauth2_scheme)], session: SessionDep
) -> User:
    user_id = verify_token(token, "access")["sub"]
    return _load_user(session, user_id)


def get_active_user(
    token: Annotated[str, Depends(oauth2_scheme)], session: SessionDep
) -> User:
    user_id = verify_token(token, "access")["sub"]
    return _load_user(session, user_id)


def get_admin_user(current_user: Annotated[User, Depends(get_active_user)]) -> User:
    """Platform staff only — the gate on every /admin route."""
    if not current_user.is_admin:
        logger.warning(
            "non-admin attempted an admin route",
            extra={"user_id": current_user.id},
        )
        raise AdminAccessRequiredError()

    return current_user


# -------------------------------------------------------------------
# WebSocket auth helper
# -------------------------------------------------------------------


def get_user_id_from_ws(websocket: WebSocket, session: Session) -> str | None:
    """Authenticate a socket from `?token=`; returns None when it must close."""
    token = websocket.query_params.get("token")
    if not token:
        logger.info("WebSocket connection missing token")
        return None

    try:
        payload = verify_token(token, expected_type="access")
        user = _load_user(session, payload["sub"])
        logger.info("WebSocket authenticated", extra={"user_id": user.id})
        return user.id
    except HTTPException:
        logger.warning("WebSocket token verification failed")
        return None
