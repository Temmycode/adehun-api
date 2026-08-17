from app.logging import get_logger
from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi.security import OAuth2PasswordRequestForm
from sqlmodel import select

from app.service import token_service
from app.database import SessionDep
from app.exceptions import BadRequestError, UserNotFoundError
from app.models import User

logger = get_logger(__name__)

router = APIRouter(prefix="/auth", tags=["Development"])


@router.post("/dev-login", include_in_schema=True)
def dev_login(
    form_data: Annotated[OAuth2PasswordRequestForm, Depends()],
    session: SessionDep,
):
    """
    **Dev only — not available in production.**

    Swagger UI login endpoint. Enter your email as the username and anything
    as the password. Returns a bearer token you can use with the Authorize
    button to test protected endpoints.

    NOTE: returns the raw OAuth2 token shape (not wrapped in APIResponse) so
    Swagger's "Authorize" flow can parse it directly.
    """

    logger.debug("dev login attempt", extra={"username": form_data.username})
    user = session.exec(select(User).where(User.email == form_data.username)).first()

    if not user:
        logger.info(
            "dev login failed, user not found",
            extra={"username": form_data.username},
        )
        raise UserNotFoundError("No user found with that email")

    if not user.active:
        logger.info(
            "dev login failed, inactive user",
            extra={"user_id": user.id, "email": user.email},
        )
        raise BadRequestError("User account is inactive")

    access_token = token_service.create_token(user.id, "access")

    logger.warning(
        "dev login used — ensure DEBUG=false in production",
        extra={"user_id": user.id, "email": user.email},
    )

    return {"access_token": access_token, "token_type": "bearer"}


@router.post("/dev-promote-admin", include_in_schema=True)
def dev_promote_admin(email: str, session: SessionDep):
    """
    **Dev only — not available in production.**

    Grant platform-admin rights to a user by email, so the /admin/disputes
    routes can be exercised locally. In production this is a deliberate SQL
    statement instead:

        UPDATE "user" SET is_admin = true WHERE email = '...';
    """
    user = session.exec(select(User).where(User.email == email)).first()

    if not user:
        raise UserNotFoundError("No user found with that email")

    user.is_admin = True
    session.add(user)
    session.commit()
    session.refresh(user)

    logger.warning(
        "user promoted to admin via dev route — ensure DEBUG=false in production",
        extra={"user_id": user.id, "email": user.email},
    )

    return {"id": user.id, "email": user.email, "is_admin": user.is_admin}
