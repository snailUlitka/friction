from pathlib import Path

from sqlalchemy import inspect, text

from friction.storage import create_sqlite_engine, current_revision, upgrade_database


def test_upgrade_creates_schema_and_fts(tmp_path: Path) -> None:
    engine = create_sqlite_engine(tmp_path / "migration.db")

    upgrade_database(engine)
    upgrade_database(engine)

    tables = set(inspect(engine).get_table_names())
    assert {
        "alembic_version",
        "events",
        "friction_items",
        "imports",
        "item_tags",
        "tags",
    }.issubset(tables)
    assert current_revision(engine) == "0001_initial"

    with engine.connect() as connection:
        fts = connection.execute(
            text(
                "SELECT name FROM sqlite_master "
                "WHERE type = 'table' AND name = 'friction_items_fts'"
            )
        ).scalar_one()
    assert fts == "friction_items_fts"

