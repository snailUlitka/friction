"""Typer command-line and versioned JSON adapter."""

from __future__ import annotations

import json
import os
import shlex
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Annotated, Any, Never, cast

import typer
from pydantic import JsonValue, ValidationError
from sqlalchemy.exc import SQLAlchemyError

from friction.application import ArchiveFilter, FrictionService, ItemQuery
from friction.contracts import (
    AddRequest,
    ItemData,
    ItemDetailData,
    ItemListData,
    UpdateRequest,
    error_envelope,
    success_envelope,
)
from friction.domain import (
    CreateItem,
    FrictionError,
    FrictionEvent,
    FrictionItem,
    ImportFailureError,
    ItemPatch,
    ItemSource,
    ItemStatus,
    StorageError,
)
from friction.interfaces.jsonl import (
    ExportResult,
    ImportReport,
    JsonlImporter,
    canonical_jsonl,
    write_jsonl_export,
)
from friction.interfaces.maintenance import backup_database, doctor_database
from friction.storage import create_repository, create_service

app = typer.Typer(help="Track workflow friction locally.")


class OutputMode(StrEnum):
    """CLI presentation format."""

    HUMAN = "human"
    JSON = "json"


class CliInputError(FrictionError):
    """Stable validation error raised by the CLI adapter."""

    code = "validation_error"


@dataclass(frozen=True)
class AppState:
    """Global command configuration."""

    database_path: Path | None


@app.callback(invoke_without_command=True)
def root(
    ctx: typer.Context,
    database: Annotated[
        Path | None,
        typer.Option("--db", help="Override the SQLite database path."),
    ] = None,
) -> None:
    """Track workflow friction locally."""
    ctx.obj = AppState(database_path=database)
    if ctx.invoked_subcommand is None:
        typer.echo(ctx.get_help())


def _state(ctx: typer.Context) -> AppState:
    return cast(AppState, ctx.obj)


def _service(ctx: typer.Context) -> FrictionService:
    return create_service(_state(ctx).database_path)


def _exit_code(code: str) -> int:
    if code in {"validation_error", "invalid_transition"}:
        return 2
    if code in {"not_found", "ambiguous_identifier"}:
        return 3
    if code == "revision_conflict":
        return 4
    if code == "import_error":
        return 6
    return 5


def _abort(error: FrictionError, output: OutputMode) -> Never:
    if output is OutputMode.JSON:
        details = cast(dict[str, JsonValue], error.details)
        _write_json(error_envelope(error.code, error.message, details=details))
    else:
        typer.echo(f"fr: {error.message}", err=True)
    raise typer.Exit(_exit_code(error.code))


def _call[T](output: OutputMode, operation: Callable[[], T]) -> T:
    try:
        return operation()
    except FrictionError as error:
        _abort(error, output)
    except ValidationError as error:
        validation_errors = cast(
            JsonValue,
            json.loads(
                json.dumps(
                    error.errors(include_url=False, include_input=False),
                    ensure_ascii=False,
                )
            ),
        )
        _abort(
            CliInputError(
                "Input does not match the Friction v1 contract.",
                details={"errors": validation_errors},
            ),
            output,
        )
    except json.JSONDecodeError as error:
        _abort(
            CliInputError(
                f"Invalid JSON at line {error.lineno}, column {error.colno}.",
                details={"line": error.lineno, "column": error.colno},
            ),
            output,
        )
    except (OSError, SQLAlchemyError) as error:
        _abort(StorageError(str(error)), output)


def _write_json(value: Any) -> None:
    typer.echo(
        json.dumps(
            value.model_dump(mode="json"),
            ensure_ascii=False,
            separators=(",", ":"),
        )
    )


def _emit_item(item: FrictionItem, output: OutputMode, *, verb: str) -> None:
    if output is OutputMode.JSON:
        _write_json(success_envelope(ItemData.from_domain(item)))
    else:
        typer.echo(f"{verb} {item.id}")


def _emit_items(items: list[FrictionItem], output: OutputMode) -> None:
    if output is OutputMode.JSON:
        _write_json(success_envelope(ItemListData.from_domain(items)))
        return
    if not items:
        typer.echo("fr: no matching items")
        return
    for item in items:
        typer.echo(_item_line(item))


def _item_line(item: FrictionItem) -> str:
    note = " ".join(item.note.split())
    location = item.path or item.cwd or item.git_repo or "-"
    tags = f" #{' #'.join(item.tags)}" if item.tags else ""
    archived = " archived" if item.archived_at else ""
    return (
        f"{str(item.id)[:8]} {item.created_at.astimezone():%Y-%m-%d %H:%M} "
        f"[{item.status.value}{archived}] {item.source.value} {location}"
        f"{tags} - {note}"
    )


def _archive_filter(archived: bool, all_items: bool) -> ArchiveFilter:
    if archived and all_items:
        raise CliInputError("--archived and --all cannot be combined.")
    if archived:
        return ArchiveFilter.ARCHIVED
    if all_items:
        return ArchiveFilter.ALL
    return ArchiveFilter.ACTIVE


def _query(
    statuses: list[ItemStatus] | None,
    sources: list[ItemSource] | None,
    repo: str | None,
    tags: list[str] | None,
    archived: bool,
    all_items: bool,
    limit: int,
    offset: int,
) -> ItemQuery:
    return ItemQuery(
        statuses=tuple(statuses or ()),
        sources=tuple(sources or ()),
        repo=repo,
        tags=tuple(tags or ()),
        archive=_archive_filter(archived, all_items),
        limit=limit,
        offset=offset,
    )


def _read_input_json(source: str) -> str:
    if source == "-":
        return sys.stdin.read()
    return Path(source).expanduser().read_text(encoding="utf-8")


def _git_value(cwd: Path, *arguments: str) -> str | None:
    try:
        result = subprocess.run(
            ["git", "-C", str(cwd), *arguments],
            capture_output=True,
            check=False,
            text=True,
            timeout=2,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    value = result.stdout.strip()
    return value if result.returncode == 0 and value else None


def _git_context(cwd: Path) -> dict[str, str | None]:
    root = _git_value(cwd, "rev-parse", "--show-toplevel")
    if root is None:
        return {
            "git_root": None,
            "git_repo": None,
            "git_branch": None,
            "git_commit": None,
        }
    root_path = Path(root)
    return {
        "git_root": str(root_path),
        "git_repo": root_path.name,
        "git_branch": _git_value(root_path, "branch", "--show-current"),
        "git_commit": _git_value(root_path, "rev-parse", "HEAD"),
    }


def _editor_command(environment: Mapping[str, str] | None = None) -> list[str]:
    environ = os.environ if environment is None else environment
    for variable in ("FRICTION_EDITOR", "VISUAL", "EDITOR"):
        value = environ.get(variable, "").strip()
        if value:
            command = shlex.split(value)
            if command and shutil.which(command[0]) is not None:
                return command
            raise CliInputError(f"Editor from {variable} is not executable.")
    raise CliInputError("Set FRICTION_EDITOR, VISUAL, or EDITOR first.")


def _launch_editor(
    target: Path,
    *,
    line: int | None = None,
    column: int | None = None,
) -> None:
    command = _editor_command()
    position: list[str] = []
    if line is not None:
        suffix = f":{column}" if column is not None else ""
        position = [f"+{line}{suffix}"]
    result = subprocess.run([*command, *position, str(target)], check=False)
    if result.returncode != 0:
        raise CliInputError(f"Editor exited with status {result.returncode}.")


def _edit_text(initial: str) -> str:
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", suffix=".txt", delete=False
        ) as temporary:
            temporary.write(initial)
            if initial and not initial.endswith("\n"):
                temporary.write("\n")
            temporary_path = Path(temporary.name)
        _launch_editor(temporary_path)
        return temporary_path.read_text(encoding="utf-8").strip()
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def _resolved_source(item: FrictionItem) -> Path:
    raw_target = item.path or item.cwd
    if raw_target is None:
        raise CliInputError("This item has no source path or working directory.")
    target = Path(raw_target).expanduser()
    if not target.is_absolute() and item.cwd:
        target = Path(item.cwd).expanduser() / target
    target = target.resolve()
    if not target.exists():
        raise CliInputError(f"Source path does not exist: {target}")
    return target


@app.command("add")
def add_item(
    ctx: typer.Context,
    note: Annotated[str | None, typer.Argument(help="Friction note.")] = None,
    edit: Annotated[
        bool, typer.Option("--edit", "-e", help="Edit the note in $EDITOR.")
    ] = False,
    input_json: Annotated[
        str | None,
        typer.Option("--input-json", help="Read a v1 request from a file or '-'."),
    ] = None,
    tags: Annotated[
        list[str] | None, typer.Option("--tag", help="Attach a repeatable tag.")
    ] = None,
    path: Annotated[str | None, typer.Option("--path")] = None,
    line: Annotated[int | None, typer.Option("--line", min=1)] = None,
    column: Annotated[int | None, typer.Option("--column", min=1)] = None,
    filetype: Annotated[str | None, typer.Option("--filetype")] = None,
    output: Annotated[OutputMode, typer.Option("--output")] = OutputMode.HUMAN,
) -> None:
    """Capture a new friction item."""

    def operation() -> FrictionItem:
        service = _service(ctx)
        if input_json is not None:
            if note is not None or edit or tags or path or line or column or filetype:
                raise CliInputError(
                    "--input-json cannot be combined with note or capture options."
                )
            request = AddRequest.model_validate_json(_read_input_json(input_json))
            return service.create(request.data.to_command())

        captured_note = note
        if edit:
            captured_note = _edit_text(captured_note or "")
        elif captured_note is None:
            captured_note = typer.prompt("what felt slow/annoying?")
        cwd = Path.cwd().resolve()
        context = _git_context(cwd)
        resolved_path = str(Path(path).expanduser().resolve()) if path else None
        return service.create(
            CreateItem(
                note=captured_note,
                source=ItemSource.CLI,
                path=resolved_path,
                line=line,
                column=column,
                cwd=str(cwd),
                filetype=filetype,
                tags=tuple(tags or ()),
                git_root=context["git_root"],
                git_repo=context["git_repo"],
                git_branch=context["git_branch"],
                git_commit=context["git_commit"],
            )
        )

    item = _call(output, operation)
    _emit_item(item, output, verb="Created")


@app.command("list")
def list_items(
    ctx: typer.Context,
    statuses: Annotated[list[ItemStatus] | None, typer.Option("--status")] = None,
    sources: Annotated[list[ItemSource] | None, typer.Option("--source")] = None,
    repo: Annotated[str | None, typer.Option("--repo")] = None,
    tags: Annotated[list[str] | None, typer.Option("--tag")] = None,
    archived: Annotated[bool, typer.Option("--archived")] = False,
    all_items: Annotated[bool, typer.Option("--all")] = False,
    limit: Annotated[int, typer.Option("--limit", min=1, max=1000)] = 100,
    offset: Annotated[int, typer.Option("--offset", min=0)] = 0,
    output: Annotated[OutputMode, typer.Option("--output")] = OutputMode.HUMAN,
) -> None:
    """List friction items newest first."""
    items = _call(
        output,
        lambda: _service(ctx).list(
            _query(
                statuses,
                sources,
                repo,
                tags,
                archived,
                all_items,
                limit,
                offset,
            )
        ),
    )
    _emit_items(items, output)


@app.command("search")
def search_items(
    ctx: typer.Context,
    text_value: Annotated[str, typer.Argument(help="Full-text query.")],
    statuses: Annotated[list[ItemStatus] | None, typer.Option("--status")] = None,
    sources: Annotated[list[ItemSource] | None, typer.Option("--source")] = None,
    repo: Annotated[str | None, typer.Option("--repo")] = None,
    tags: Annotated[list[str] | None, typer.Option("--tag")] = None,
    archived: Annotated[bool, typer.Option("--archived")] = False,
    all_items: Annotated[bool, typer.Option("--all")] = False,
    limit: Annotated[int, typer.Option("--limit", min=1, max=1000)] = 100,
    offset: Annotated[int, typer.Option("--offset", min=0)] = 0,
    output: Annotated[OutputMode, typer.Option("--output")] = OutputMode.HUMAN,
) -> None:
    """Search notes, tags, and source context."""
    items = _call(
        output,
        lambda: _service(ctx).search(
            text_value,
            _query(
                statuses,
                sources,
                repo,
                tags,
                archived,
                all_items,
                limit,
                offset,
            ),
        ),
    )
    _emit_items(items, output)


@app.command("show")
def show_item(
    ctx: typer.Context,
    identifier: str,
    history: Annotated[bool, typer.Option("--history")] = False,
    output: Annotated[OutputMode, typer.Option("--output")] = OutputMode.HUMAN,
) -> None:
    """Show one item and optionally its event history."""

    def operation() -> tuple[FrictionItem, list[FrictionEvent]]:
        service = _service(ctx)
        item = service.get(identifier)
        events = service.events(identifier) if history else []
        return item, events

    item, events = _call(output, operation)
    if output is OutputMode.JSON:
        _write_json(success_envelope(ItemDetailData.from_domain(item, events)))
        return
    typer.echo(f"id: {item.id}")
    typer.echo(f"status: {item.status.value}")
    typer.echo(f"revision: {item.revision}")
    typer.echo(f"source: {item.source.value}")
    typer.echo(f"created_at: {item.created_at.isoformat()}")
    typer.echo(f"updated_at: {item.updated_at.isoformat()}")
    archived_at = item.archived_at.isoformat() if item.archived_at else "-"
    typer.echo(f"archived_at: {archived_at}")
    typer.echo(f"path: {item.path or '-'}")
    typer.echo(f"cwd: {item.cwd or '-'}")
    typer.echo(f"tags: {', '.join(item.tags) if item.tags else '-'}")
    typer.echo("note:")
    typer.echo(item.note)
    for event_value in events:
        typer.echo(
            f"event: {event_value.occurred_at.isoformat()} "
            f"{event_value.event_type.value} r{event_value.to_revision}"
        )


@app.command("update")
def update_item(
    ctx: typer.Context,
    identifier: str,
    input_json: Annotated[
        str, typer.Option("--input-json", help="Read a v1 request from a file or '-'.")
    ],
    output: Annotated[OutputMode, typer.Option("--output")] = OutputMode.HUMAN,
) -> None:
    """Apply a versioned JSON patch."""

    def operation() -> FrictionItem:
        request = UpdateRequest.model_validate_json(_read_input_json(input_json))
        return _service(ctx).update(
            identifier,
            request.data.to_patch(),
            expected_revision=request.data.revision,
        )

    item = _call(output, operation)
    _emit_item(item, output, verb="Updated")


@app.command("edit")
def edit_item(
    ctx: typer.Context,
    identifier: str,
    output: Annotated[OutputMode, typer.Option("--output")] = OutputMode.HUMAN,
) -> None:
    """Edit only the note with optimistic concurrency."""

    def operation() -> FrictionItem:
        service = _service(ctx)
        current = service.get(identifier)
        note = _edit_text(current.note)
        return service.update(
            current.id,
            ItemPatch(note=note),
            expected_revision=current.revision,
        )

    item = _call(output, operation)
    _emit_item(item, output, verb="Updated")


def _lifecycle_command(
    ctx: typer.Context,
    identifier: str,
    revision: int | None,
    output: OutputMode,
    action: str,
) -> None:
    def operation() -> FrictionItem:
        service = _service(ctx)
        current = service.get(identifier)
        expected = revision or current.revision
        if action == "done":
            return service.mark_done(current.id, expected_revision=expected)
        if action == "dismiss":
            return service.dismiss(current.id, expected_revision=expected)
        if action == "reopen":
            return service.reopen(current.id, expected_revision=expected)
        if action == "unarchive":
            return service.unarchive(current.id, expected_revision=expected)
        raise CliInputError(f"Unsupported lifecycle action: {action}")

    item = _call(output, operation)
    _emit_item(item, output, verb=action.capitalize())


@app.command("done")
def mark_done(
    ctx: typer.Context,
    identifier: str,
    revision: Annotated[int | None, typer.Option("--revision", min=1)] = None,
    output: Annotated[OutputMode, typer.Option("--output")] = OutputMode.HUMAN,
) -> None:
    """Mark an open item done."""
    _lifecycle_command(ctx, identifier, revision, output, "done")


@app.command("dismiss")
def dismiss_item(
    ctx: typer.Context,
    identifier: str,
    revision: Annotated[int | None, typer.Option("--revision", min=1)] = None,
    output: Annotated[OutputMode, typer.Option("--output")] = OutputMode.HUMAN,
) -> None:
    """Dismiss an open item."""
    _lifecycle_command(ctx, identifier, revision, output, "dismiss")


@app.command("reopen")
def reopen_item(
    ctx: typer.Context,
    identifier: str,
    revision: Annotated[int | None, typer.Option("--revision", min=1)] = None,
    output: Annotated[OutputMode, typer.Option("--output")] = OutputMode.HUMAN,
) -> None:
    """Reopen a done or dismissed item."""
    _lifecycle_command(ctx, identifier, revision, output, "reopen")


@app.command("archive")
def archive_item(
    ctx: typer.Context,
    identifier: Annotated[str | None, typer.Argument()] = None,
    status: Annotated[ItemStatus | None, typer.Option("--status")] = None,
    revision: Annotated[int | None, typer.Option("--revision", min=1)] = None,
    yes: Annotated[bool, typer.Option("--yes", help="Confirm a bulk archive.")] = False,
    output: Annotated[OutputMode, typer.Option("--output")] = OutputMode.HUMAN,
) -> None:
    """Archive one item or all active items with a status."""

    def operation() -> list[FrictionItem]:
        if (identifier is None) == (status is None):
            raise CliInputError("Provide either an item ID or --status.")
        service = _service(ctx)
        if identifier is not None:
            current = service.get(identifier)
            expected = revision or current.revision
            return [service.archive(current.id, expected_revision=expected)]
        if revision is not None:
            raise CliInputError("--revision is only valid when archiving one item.")
        candidates = service.list(ItemQuery(statuses=(cast(ItemStatus, status),)))
        if candidates and not yes and not typer.confirm(
            f"Archive {len(candidates)} matching item(s)?"
        ):
            raise typer.Abort()
        return [
            service.archive(item.id, expected_revision=item.revision)
            for item in candidates
        ]

    items = _call(output, operation)
    if len(items) == 1 and identifier is not None:
        _emit_item(items[0], output, verb="Archived")
    else:
        _emit_items(items, output)


@app.command("unarchive")
def unarchive_item(
    ctx: typer.Context,
    identifier: str,
    revision: Annotated[int | None, typer.Option("--revision", min=1)] = None,
    output: Annotated[OutputMode, typer.Option("--output")] = OutputMode.HUMAN,
) -> None:
    """Restore an archived item."""
    _lifecycle_command(ctx, identifier, revision, output, "unarchive")


@app.command("open")
def open_item(
    ctx: typer.Context,
    identifier: str,
    output: Annotated[OutputMode, typer.Option("--output")] = OutputMode.HUMAN,
) -> None:
    """Open an item's source location in the configured editor."""

    def operation() -> FrictionItem:
        item = _service(ctx).get(identifier)
        _launch_editor(_resolved_source(item), line=item.line, column=item.column)
        return item

    item = _call(output, operation)
    _emit_item(item, output, verb="Opened")


@app.command("import-jsonl")
def import_jsonl(
    ctx: typer.Context,
    source: Annotated[Path, typer.Argument(help="JSONL file or directory.")],
    dry_run: Annotated[
        bool, typer.Option("--dry-run", help="Validate without touching a database.")
    ] = False,
    output: Annotated[OutputMode, typer.Option("--output")] = OutputMode.HUMAN,
) -> None:
    """Validate and idempotently import legacy or canonical JSONL."""

    def operation() -> ImportReport:
        repository = None
        if not dry_run:
            repository = create_repository(_state(ctx).database_path)
        return JsonlImporter(repository).run(source, dry_run=dry_run)

    report = _call(output, operation)
    if not report.ok:
        _abort(
            ImportFailureError(
                f"Import found {len(report.issues)} invalid JSONL record(s).",
                details=report.as_dict(),
            ),
            output,
        )
    if output is OutputMode.JSON:
        _write_json(success_envelope(report.as_dict()))
    elif dry_run:
        typer.echo(
            f"fr: dry-run validated {report.valid_records} record(s) "
            f"from {report.files} file(s)"
        )
    else:
        typer.echo(
            f"fr: imported {report.imported} record(s), skipped {report.skipped} "
            f"from {report.files} file(s)"
        )


@app.command("export")
def export_jsonl(
    ctx: typer.Context,
    export_format: Annotated[str, typer.Option("--format")] = "jsonl",
    destination: Annotated[
        Path | None,
        typer.Option("--output", help="Output file or directory; defaults to stdout."),
    ] = None,
    statuses: Annotated[list[ItemStatus] | None, typer.Option("--status")] = None,
    sources: Annotated[list[ItemSource] | None, typer.Option("--source")] = None,
    tags: Annotated[list[str] | None, typer.Option("--tag")] = None,
    force: Annotated[bool, typer.Option("--force")] = False,
) -> None:
    """Export canonical JSONL v1 to stdout, a file, or a directory."""

    def operation() -> ExportResult:
        if export_format != "jsonl":
            raise CliInputError("Only --format jsonl is supported.")
        result = canonical_jsonl(
            _service(ctx),
            statuses=tuple(statuses or ()),
            sources=tuple(sources or ()),
            tags=tuple(tags or ()),
        )
        if destination is not None:
            result = write_jsonl_export(result, destination, force=force)
        return result

    result = _call(OutputMode.HUMAN, operation)
    if result.path is not None:
        typer.echo(f"fr: exported {result.count} item(s) to {result.path}")
    else:
        for line in result.lines:
            typer.echo(line)


@app.command("backup")
def backup(
    ctx: typer.Context,
    destination: Annotated[Path, typer.Argument(help="Backup file or directory.")],
    force: Annotated[bool, typer.Option("--force")] = False,
    output: Annotated[OutputMode, typer.Option("--output")] = OutputMode.HUMAN,
) -> None:
    """Create a verified online SQLite backup."""
    result = _call(
        output,
        lambda: backup_database(
            _state(ctx).database_path, destination, force=force
        ),
    )
    if output is OutputMode.JSON:
        _write_json(success_envelope(result.as_dict()))
    else:
        typer.echo(f"fr: backed up database to {result.path} ({result.size} bytes)")


@app.command("doctor")
def doctor(
    ctx: typer.Context,
    output: Annotated[OutputMode, typer.Option("--output")] = OutputMode.HUMAN,
) -> None:
    """Check the database, migrations, FTS, editor, and Git."""
    report = _call(output, lambda: doctor_database(_state(ctx).database_path))
    if not report.ok:
        _abort(
            StorageError(
                "One or more required doctor checks failed.",
                details=report.as_dict(),
            ),
            output,
        )
    if output is OutputMode.JSON:
        _write_json(success_envelope(report.as_dict()))
    else:
        for check in report.checks:
            typer.echo(f"{check.status:7} {check.name}: {check.detail}")


def main() -> None:
    """Run the command-line interface."""
    app()
