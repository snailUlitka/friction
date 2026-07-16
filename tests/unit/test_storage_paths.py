from pathlib import Path

from friction.storage.sqlite import default_database_path, resolve_database_path


def test_explicit_path_precedes_environment(tmp_path: Path) -> None:
    explicit = tmp_path / "explicit.db"
    environment = {"FRICTION_DB_PATH": str(tmp_path / "environment.db")}

    assert resolve_database_path(explicit, environment=environment) == explicit


def test_environment_precedes_default(tmp_path: Path) -> None:
    configured = tmp_path / "configured.db"

    assert resolve_database_path(
        environment={"FRICTION_DB_PATH": str(configured)}
    ) == configured


def test_default_path_is_macos_application_support() -> None:
    assert default_database_path().parts[-4:] == (
        "Library",
        "Application Support",
        "friction",
        "friction.db",
    )
