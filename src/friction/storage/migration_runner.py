"""Programmatic Alembic migration runner."""

from importlib.resources import files

from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from sqlalchemy import Engine


def _config() -> Config:
    config = Config()
    location = files("friction.storage").joinpath("migrations")
    config.set_main_option("script_location", str(location))
    return config


def upgrade_database(engine: Engine) -> None:
    """Upgrade a database to the latest packaged migration."""
    config = _config()
    with engine.begin() as connection:
        config.attributes["connection"] = connection
        command.upgrade(config, "head")


def current_revision(engine: Engine) -> str | None:
    """Return the current Alembic revision, if initialized."""
    with engine.connect() as connection:
        return MigrationContext.configure(connection).get_current_revision()

