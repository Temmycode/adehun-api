from datetime import datetime, timedelta, timezone
from typing import Annotated

import jwt
from fastapi import Depends, HTTPException
from fastapi.security import OAuth2PasswordBearer

from app.database import SessionDep
from app.models import User

from .config import settings

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="auth/login")

SECRET_KEY = settings.secret_key
ALGORITHM = settings.algorithm
ACCESS_TOKEN_EXPIRATION_MINUTES = settings.access_token_expiration_minutes
REFRESH_TOKEN_EXPIRATION_DAYS = settings.refresh_token_expiration_minutes


# ------------------------------------------------------------------
# Token Creation
# ------------------------------------------------------------------


def create_token(
    user_id: str,
    token_type: str,
    expires_delta: timedelta | None = None,
    extra_claims: dict | None = None,
):
    expire_delta = (
        timedelta(minutes=ACCESS_TOKEN_EXPIRATION_MINUTES)
        if token_type == "access"
        else timedelta(days=REFRESH_TOKEN_EXPIRATION_DAYS)
    )

    expire = (
        datetime.now(timezone.utc) + expires_delta if expires_delta else expire_delta
    )

    payload = {
        "user_id": user_id,
        "type": token_type,
        "exp": expire,
    }

    if extra_claims:
        payload.update(extra_claims)

    encoded_jwt = jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt


# ------------------------------------------------------------------
# Token Verification
# ------------------------------------------------------------------


def verify_token(token: str, expected_type: str):
    # Verify the token and return the user information
    credentials_exception = HTTPException(
        status_code=401,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])

        if payload.get("type") != expected_type:
            raise credentials_exception

        if payload.get("sub") is None:
            raise credentials_exception

        return payload
    except jwt.PyJWTError as exc:
        raise credentials_exception from exc


# ------------------------------------------------------------------
# FastAPI dependencies
# ------------------------------------------------------------------


def get_current_user(
    token: Annotated[str, Depends(oauth2_scheme)], session: SessionDep
):
    user_id = verify_token(token, "access")["sub"]

    # Fetch user information from the database
    user = session.get(User, user_id)
    if not user:
        raise HTTPException(
            status_code=401,
            detail="Could not validate credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return user


def get_active_user(token: Annotated[str, Depends(oauth2_scheme)], session: SessionDep):
    user_id = verify_token(token, "access")["sub"]

    # Fetch user information from the database
    user = session.get(User, user_id)
    if not user:
        raise HTTPException(
            status_code=401,
            detail="Could not validate credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not user.active == 0:
        raise HTTPException(
            status_code=400,
            detail="Inactive user",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return user
