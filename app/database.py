from typing import Annotated
from urllib.parse import quote_plus

from fastapi import Depends
from sqlmodel import Session, create_engine

from app.config import settings
from app.logging import get_logger

logger = get_logger(__name__)


def build_database_url() -> str:
    """Compose the Postgres URL, escaping credentials that contain URL chars.

    A hostname starting with "/" is a Unix socket directory (local Homebrew
    Postgres), which libpq wants as `?host=` rather than in the authority.
    """
    credentials = (
        f"{quote_plus(settings.database_username)}:"
        f"{quote_plus(settings.database_password)}"
    )
    host = settings.database_hostname
    if host.startswith("/"):
        return (
            f"postgresql://{credentials}@/{settings.database_name}"
            f"?host={quote_plus(host)}&port={settings.database_port}"
        )
    return (
        f"postgresql://{credentials}@{host}:{settings.database_port}/"
        f"{settings.database_name}"
    )


postgres_url = build_database_url()

engine = create_engine(
    postgres_url,
    # Hosted Postgres reaps idle connections; pre-ping swaps a dead one for a
    # fresh connection instead of surfacing a 500 on the first request.
    pool_pre_ping=True,
    pool_size=5,
    max_overflow=10,
    pool_recycle=1800,
    connect_args={"sslmode": settings.database_sslmode},
)


def get_session():
    with Session(engine) as session:
        yield session


SessionDep = Annotated[Session, Depends(get_session)]
