import sys
from pathlib import Path
from typing import Annotated

import typer

from podcleaner_clips import __version__, config
from podcleaner_clips.errors import ClipsError

app = typer.Typer(
    help="Cut the movie clips noted while watching.",
    no_args_is_help=True,
    pretty_exceptions_enable=False,
)


@app.callback()
def _root() -> None:
    """Keeps subcommands even when there is only one."""


config_app = typer.Typer(help="Create or show the configuration file.", no_args_is_help=True)
app.add_typer(config_app, name="config")

ConfigOption = Annotated[
    Path | None,
    typer.Option(
        "--config",
        help=f"Configuration file (else {config.CONFIG_ENV_VAR}, then the usual location).",
    ),
]


@app.command()
def version() -> None:
    """Show the version."""
    typer.echo(__version__)


@config_app.command("init")
def config_init(config_path: ConfigOption = None) -> None:
    """Create a commented configuration file to fill in."""
    path = config.resolve_config_path(config_path)
    config.write_template(path)
    typer.echo(f"Configuration file created: {path}")
    typer.echo("Open it and set at least dossier_episodes and son_transition.")


@config_app.command("show")
def config_show(config_path: ConfigOption = None) -> None:
    """Show the configuration as read, defaults included."""
    path = config.resolve_config_path(config_path)
    settings = config.load_settings(path)
    typer.echo(f"File: {path}")
    for key, value in config.describe(settings):
        typer.echo(f"{key} = {value}")


def main() -> None:
    # Click standalone mode handles usage errors itself (exit code 2);
    # ClipsError is not a Click exception, so it propagates up to here.
    try:
        app()
    except ClipsError as exc:
        typer.echo(f"Error: {exc}", err=True)
        sys.exit(2)
