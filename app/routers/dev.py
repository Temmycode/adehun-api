import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import OAuth2PasswordRequestForm
from sqlmodel import select

from app import token_service
from app.database import SessionDep
from app.models import User

logger = logging.getLogger(__name__)

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
    """

    logger.debug("dev_login: username=%s", form_data.username)
    user = session.exec(select(User).where(User.email == form_data.username)).first()

    if not user:
        raise HTTPException(status_code=404, detail="No user found with that email")

    if not user.active:
        raise HTTPException(status_code=400, detail="User account is inactive")

    access_token = token_service.create_token(user.user_id, "access")

    logger.warning(
        "Dev login used for user email=%s — ensure DEBUG=false in production",
        user.email,
    )

    return {"access_token": access_token, "token_type": "bearer"}
