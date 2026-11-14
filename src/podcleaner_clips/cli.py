import sys
from pathlib import Path
from typing import Annotated

import typer

from podcleaner_clips import __version__, config, prog_name
from podcleaner_clips.errors import ClipsError

app = typer.Typer(
    help="Cut the movie clips noted while watching.",
    invoke_without_command=True,
    pretty_exceptions_enable=False,
)

ConfigOption = Annotated[
    Path | None,
    typer.Option(
        "--config",
        help=f"Configuration file (else {config.CONFIG_ENV_VAR}, then the usual location).",
    ),
]


def _print_version(value: bool) -> None:
    if value:
        typer.echo(__version__)
        raise typer.Exit()


@app.callback()
def _root(
    ctx: typer.Context,
    _version: Annotated[
        bool,
        typer.Option(
            "--version", callback=_print_version, is_eager=True, help="Show the version and exit."
        ),
    ] = False,
) -> None:
    """Cut the movie clips noted while watching."""
    if ctx.invoked_subcommand is None:  # the command alone: its help, not an error
        typer.echo(ctx.get_help())


def _stdin_is_tty() -> bool:
    return sys.stdin.isatty()


@app.command("init")
def init_command(
    config_path: ConfigOption = None,
    no_input: Annotated[
        bool,
        typer.Option("--no-input", help="Ask nothing: write the commented file to fill in."),
    ] = False,
) -> None:
    """Create your configuration file by answering a few questions."""
    path = config.resolve_config_path(config_path)
    if not no_input and _stdin_is_tty():
        from podcleaner_clips.wizard import run_wizard

        run_wizard(path)
        return
    config.write_template(path)
    typer.echo(f"Configuration file created: {path}")
    typer.echo("Open it and set at least episodes_dir and transition_sound.")


def _show(config_path: Path | None) -> None:
    path = config.resolve_config_path(config_path)
    settings = config.load_settings(path)
    typer.echo(f"File: {path}")
    for key, value in config.describe(settings):
        typer.echo(f"{key} = {value}")
    for notice in settings.notices:
        typer.echo(f"⚠ {notice}", err=True)


config_app = typer.Typer(invoke_without_command=True)
app.add_typer(config_app, name="config")


@config_app.callback()
def config_command(
    ctx: typer.Context,
    path_only: Annotated[
        bool, typer.Option("--path", help="Only print where the configuration file is.")
    ] = False,
    config_path: ConfigOption = None,
) -> None:
    """Show the configuration as read, defaults included."""
    if ctx.invoked_subcommand is not None:
        return
    if path_only:
        typer.echo(config.resolve_config_path(config_path))
    else:
        _show(config_path)


# Older spellings, kept working but hidden from the help.
@config_app.command("show", hidden=True)
def config_show(config_path: ConfigOption = None) -> None:
    _show(config_path)


@config_app.command("init", hidden=True)
def config_init(config_path: ConfigOption = None) -> None:
    init_command(config_path, no_input=False)


@app.command("run")
def run_command(
    notes: Annotated[Path, typer.Argument(help="Notes file of the film (one clip per line).")],
    film: Annotated[
        Path | None, typer.Option("--film", help="The film (else `file:` in the notes).")
    ] = None,
    no_transition: Annotated[
        bool, typer.Option("--no-transition", help="No transition sound, no black screen.")
    ] = False,
    audio_only: Annotated[bool, typer.Option("--audio-only", help="Only the WAV files.")] = False,
    video_only: Annotated[bool, typer.Option("--video-only", help="Only the MP4 files.")] = False,
    no_adjust: Annotated[
        bool,
        typer.Option("--no-adjust", help="Cut at the noted timecodes (no Whisper, no Claude)."),
    ] = False,
    dry_run: Annotated[
        bool, typer.Option("--dry-run", help="Find the cuts and show them, write nothing.")
    ] = False,
    audio_track: Annotated[
        int | None,
        typer.Option("--audio-track", help="Audio track to use (number from 0), if mislabelled."),
    ] = None,
    config_path: ConfigOption = None,
) -> None:
    """Cut the clips noted for a film; only what changed since the last run is redone."""
    from podcleaner_clips.pipeline import RunOptions, run  # Whisper and numpy load lazily

    report = run(
        RunOptions(
            notes=notes,
            film=film,
            transition=not no_transition,
            audio=not video_only,
            video=not audio_only,
            adjust=not no_adjust,
            dry_run=dry_run,
            audio_track=audio_track,
            config=config_path,
        )
    )
    if report.failures:
        raise typer.Exit(1)


@app.command()
def version() -> None:
    """Show the version."""
    typer.echo(__version__)


def main() -> None:
    # Click standalone mode handles usage errors itself (exit code 2);
    # ClipsError is not a Click exception, so it propagates up to here.
    try:
        app(prog_name=prog_name())
    except ClipsError as exc:
        typer.echo(f"Error: {exc}", err=True)
        sys.exit(2)
