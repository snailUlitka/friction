"""Console entry point."""

import typer

app = typer.Typer(help="Track workflow friction locally.")


@app.callback(invoke_without_command=True)
def root(ctx: typer.Context) -> None:
    """Track workflow friction locally."""
    if ctx.invoked_subcommand is None:
        typer.echo(ctx.get_help())


def main() -> None:
    """Run the command-line interface."""
    app()

