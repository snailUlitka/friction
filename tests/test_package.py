import re
import tomllib
from pathlib import Path

from typer.testing import CliRunner

from friction import __version__
from friction.cli import app

ROOT = Path(__file__).resolve().parents[1]


def test_package_version() -> None:
    with (ROOT / "pyproject.toml").open("rb") as file:
        project_version = tomllib.load(file)["project"]["version"]
    emacs_source = (ROOT / "integrations/emacs/friction.el").read_text()
    emacs_version = re.search(r"^;; Version: (\S+)$", emacs_source, re.MULTILINE)

    assert emacs_version is not None
    assert __version__ == project_version == emacs_version.group(1)


def test_cli_displays_version() -> None:
    result = CliRunner().invoke(app, ["--version"])

    assert result.exit_code == 0
    assert result.stdout == f"friction {__version__}\n"


def test_cli_displays_help_without_a_command() -> None:
    result = CliRunner().invoke(app)

    assert result.exit_code == 0
    assert "Track workflow friction locally" in result.stdout
