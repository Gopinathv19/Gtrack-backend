"""Alembic environment configuration."""
from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine, pool

from app.core.config import settings
from app.db.base_class import Base
import app.models  # noqa: F401  Import all models so metadata is populated

config = context.config

# NOTE: we intentionally do NOT call ``config.set_main_option("sqlalchemy.url", ...)``
# here. ConfigParser performs `%`-interpolation on values written to the ini
# section, which breaks URL-encoded passwords (e.g. ``%40`` for ``@``) and
# raises ``ValueError: invalid interpolation syntax``. Instead, we pull the
# URL directly from settings at engine-creation time and bypass the ini.
DATABASE_URL = settings.DATABASE_URL

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=DATABASE_URL,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    # Build the engine directly from the live settings URL so URL-encoded
    # characters (``%XX``) pass through untouched.
    connectable = create_engine(
        DATABASE_URL,
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
