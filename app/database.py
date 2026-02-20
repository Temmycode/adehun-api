import logging
from typing import Annotated

from fastapi import Depends
from sqlmodel import Session, SQLModel, create_engine

from app.config import settings

logger = logging.getLogger(__name__)

postgres_url = f"postgresql://{settings.database_username}:{settings.database_password}@{settings.database_hostname}:{settings.database_port}/{settings.database_name}"

engine = create_engine(postgres_url)


def create_db_and_tables():
    from app.models import (
        Agreement,
        AgreementParticipant,
        Asset,
        Condition,
        Transaction,
        User,
    )

    SQLModel.metadata.create_all(engine)
    logger.info("Database tables created")


def get_session():
    with Session(engine) as session:
        yield session


SessionDep = Annotated[Session, Depends(get_session)]
