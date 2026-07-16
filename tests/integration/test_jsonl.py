from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import text

from friction.application import ArchiveFilter, FrictionService, ItemQuery
from friction.domain import CreateItem, ItemSource, ItemStatus, StorageError
from friction.interfaces.jsonl import (
    JsonlImporter,
    canonical_jsonl,
    plan_jsonl,
    write_jsonl_export,
)
from friction.interfaces.maintenance import backup_database, doctor_database
from friction.storage import create_repository, create_sqlite_engine, upgrade_database

FIXTURES = Path(__file__).parents[1] / "fixtures" / "jsonl"


def test_planner_normalizes_all_legacy_shapes_without_storage() -> None:
    plans = plan_jsonl(FIXTURES / "legacy.jsonl")

    assert len(plans) == 1
    assert not plans[0].issues
    cli_item, emacs_item, nvim_item = [record.item for record in plans[0].records]
    assert cli_item.cwd == "/tmp/project"
    assert cli_item.path is None
    assert cli_item.created_at == datetime(2026, 5, 5, 6, tzinfo=UTC)
    assert emacs_item.filetype == "emacs-lisp-mode"
    assert emacs_item.git_root == "/tmp/configs"
    assert emacs_item.git_repo == "configs"
    assert nvim_item.filetype == "python"
    assert nvim_item.path == "/tmp/project/app.py"


def test_import_is_idempotent_and_records_provenance(tmp_path: Path) -> None:
    repository = create_repository(tmp_path / "friction.db")
    importer = JsonlImporter(repository)

    first = importer.run(FIXTURES / "legacy.jsonl")
    second = importer.run(FIXTURES / "legacy.jsonl")

    assert first.imported == 3
    assert first.skipped == 0
    assert second.imported == 0
    assert second.skipped == 3
    assert len(repository.list(ItemQuery(archive=ArchiveFilter.ALL))) == 3
    with repository.engine.connect() as connection:
        provenance_count = connection.execute(
            text("SELECT count(*) FROM imports")
        ).scalar_one()
    assert provenance_count == 3


def test_import_is_atomic_per_file_and_preserves_identical_lines(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source"
    source.mkdir()
    good_line = (FIXTURES / "legacy.jsonl").read_text(encoding="utf-8").splitlines()[0]
    (source / "duplicates.jsonl").write_text(
        f"{good_line}\n{good_line}\n", encoding="utf-8"
    )
    (source / "invalid.jsonl").write_text(
        f"{good_line}\nnot-json\n", encoding="utf-8"
    )
    repository = create_repository(tmp_path / "friction.db")

    report = JsonlImporter(repository).run(source)
    repeated = JsonlImporter(repository).run(source / "duplicates.jsonl")

    assert len(report.issues) == 1
    assert report.imported == 2
    assert len(repository.list(ItemQuery(archive=ArchiveFilter.ALL))) == 2
    assert repeated.imported == 0
    assert repeated.skipped == 2


def test_canonical_export_round_trips_current_item_state(tmp_path: Path) -> None:
    source_repository = create_repository(tmp_path / "source.db")
    source_service = FrictionService(source_repository)
    item = source_service.create(
        CreateItem(
            note="round trip",
            source=ItemSource.NVIM,
            path="/tmp/example.py",
            line=4,
            tags=("Editor",),
        )
    )
    done = source_service.mark_done(item.id, expected_revision=1)
    archived = source_service.archive(done.id, expected_revision=2)
    export = canonical_jsonl(source_service)
    written = write_jsonl_export(
        export,
        tmp_path / "exports",
        clock=lambda: datetime(2026, 7, 16, tzinfo=UTC),
    )

    target_repository = create_repository(tmp_path / "target.db")
    assert written.path is not None
    report = JsonlImporter(target_repository).run(written.path)
    restored = target_repository.get(archived.id)

    assert report.imported == 1
    assert restored == archived
    assert restored.status is ItemStatus.DONE
    assert written.path == tmp_path / "exports" / "friction-v1-20260716T000000Z.jsonl"

    with pytest.raises(StorageError):
        write_jsonl_export(export, written.path)


def test_backup_and_doctor_verify_database(tmp_path: Path) -> None:
    database = tmp_path / "friction.db"
    repository = create_repository(database)
    FrictionService(repository).create(CreateItem(note="back me up"))

    backup = backup_database(
        database,
        tmp_path / "backups",
        clock=lambda: datetime(2026, 7, 16, tzinfo=UTC),
    )
    report = doctor_database(database)
    backup_engine = create_sqlite_engine(backup.path)
    upgrade_database(backup_engine)
    backup_items = create_repository(backup.path).list(
        ItemQuery(archive=ArchiveFilter.ALL)
    )

    assert backup.path.name == "friction-backup-20260716T000000Z.db"
    assert backup.size > 0
    assert len(backup.sha256) == 64
    assert [item.note for item in backup_items] == ["back me up"]
    assert report.ok
    assert {check.name for check in report.checks} >= {
        "schema_revision",
        "integrity",
        "fts5",
    }

    with pytest.raises(StorageError):
        backup_database(database, backup.path)
