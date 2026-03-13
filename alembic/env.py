from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool
from sqlmodel import SQLModel
from sqlmodel.sql.sqltypes import AutoString

from alembic import context
from app.config import settings
from app.models.agreement import Agreement  # noqa: F401
from app.models.agreement_participant import AgreementParticipant  # noqa: F401
from app.models.asset import Asset  # noqa: F401
from app.models.asset_file import AssetFile  # noqa: F401
from app.models.condition import Condition  # noqa: F401
from app.models.invitation import Invitation  # noqa: F401
from app.models.transaction import Transaction  # noqa: F401

# Import all models so SQLAlchemy registers them in the metadata before
# autogenerate inspects it. The order here matters — tables with no
# dependencies come first, then tables that reference them.
from app.models.user import User  # noqa: F401

# Alembic Config object — provides access to values in alembic.ini
config = context.config

# Set the DB URL programmatically from app settings so we never hardcode
# credentials in alembic.ini
config.set_main_option(
    "sqlalchemy.url",
    f"postgresql://{settings.database_username}:{settings.database_password}"
    f"@{settings.database_hostname}:{settings.database_port}/{settings.database_name}",
)

# Set up Python logging from the alembic.ini [loggers] section
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Point autogenerate at SQLModel's shared metadata, which all models
# above have registered themselves into
target_metadata = SQLModel.metadata


def render_item(type_, obj, autogen_context):
    """Render SQLModel's AutoString as plain sa.String() in migration files.

    Without this, autogenerate writes sqlmodel.sql.sqltypes.AutoString() for
    every string column but never imports sqlmodel, causing a NameError when
    the migration runs.
    """
    if type_ == "type" and isinstance(obj, AutoString):
        autogen_context.imports.add("import sqlalchemy as sa")
        return "sa.String()"
    return False


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    Configures the context with just a URL rather than a live Engine.
    Useful for generating SQL scripts without a DB connection.
    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        render_item=render_item,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode.

    Creates an Engine and associates a connection with the context.
    This is the mode used when running `alembic upgrade head`.
    """
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            render_item=render_item,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
