from typer.testing import CliRunner

from friction import __version__
from friction.cli import app


def test_package_version() -> None:
    assert __version__ == "0.1.0"


def test_cli_displays_help_without_a_command() -> None:
    result = CliRunner().invoke(app)

    assert result.exit_code == 0
    assert "Track workflow friction locally" in result.stdout
