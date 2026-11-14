"""`init`: questions in the console that write the configuration file."""

import os
import re
from pathlib import Path
from typing import Any

import typer

from podcleaner_clips import claude, config, prog_name
from podcleaner_clips.errors import ClipsError
from podcleaner_clips.media import probe

_REMOVE = "-"  # answer that clears an optional path
_SHELL_ESCAPE = re.compile(r"\\(.)")  # macOS Terminal escapes a dragged path: My\ Film.mkv


def clean_path(text: str, *, windows: bool = os.name == "nt") -> str:
    """A path as pasted or dragged into the terminal: no quotes around it, no shell escapes."""
    text = text.strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in "'\"":
        text = text[1:-1]
    elif not windows:
        text = _SHELL_ESCAPE.sub(r"\1", text)
    return text


def _absolute(text: str) -> Path:
    path = Path(clean_path(text)).expanduser()
    return path if path.is_absolute() else Path.cwd() / path


def _existing(path: Path) -> dict[str, Any]:
    """The current file's values, so that each question offers them as its default."""
    if not path.is_file():
        return {}
    try:
        return config.settings_values(config.load_settings(path))
    except ClipsError as exc:
        typer.echo(f"⚠ The current file cannot be read ({exc}); starting from the defaults.")
        return {}


def _ask_episodes_dir(current: Path | None) -> Path:
    while True:
        answer = typer.prompt(
            "Folder where clips are stored (one subfolder per film)",
            default=str(current) if current else None,
        )
        path = _absolute(answer)
        if path.is_dir():
            return path
        if path.exists():
            typer.echo(f"{path} is a file, not a folder.")
            continue
        if typer.confirm(f"{path} does not exist. Create it?", default=True):
            path.mkdir(parents=True)
        return path


def _ask_optional(question: str, current: Path | None) -> str | None:
    """The answer, or None when skipped; `-` drops the current value."""
    hint = f"Enter keeps it, {_REMOVE} removes it" if current else "Enter to skip"
    answer = typer.prompt(
        f"{question} ({hint})",
        default=str(current) if current else "",
        show_default=current is not None,
    ).strip()
    return None if answer in ("", _REMOVE) else answer  # Enter returns the current value


def _ask_films_dir(current: Path | None) -> Path | None:
    while True:
        answer = _ask_optional("Folder where your films are", current)
        if answer is None:
            return None
        path = _absolute(answer)
        if path.is_dir():
            return path
        typer.echo(f"No folder at {path}.")


def _sound_problem(path: Path) -> str | None:
    if not path.is_file():
        return f"No file at {path}."
    try:
        info = probe(path)
    except ClipsError as exc:
        return str(exc)
    if not info.audio or info.duration <= 0:
        return f"{path.name} has no sound."
    return None


def _ask_transition_sound(current: Path | None) -> Path | None:
    while True:
        answer = _ask_optional("Sound played before and after each clip", current)
        if answer is None:
            typer.echo("Without a transition sound, run needs --no-transition.")
            return None
        path = _absolute(answer)
        problem = _sound_problem(path)
        if problem is None:
            return path
        typer.echo(problem)


def _video_problem(path: Path) -> str | None:
    if not path.is_file():
        return f"No file at {path}."
    try:
        info = probe(path)
    except ClipsError as exc:
        return str(exc)
    return None if info.video is not None else f"{path.name} has no picture."


def _ask_transition_video(current: Path | None) -> Path | None:
    while True:
        answer = _ask_optional(
            "Video shown during the transition sound, instead of a black screen", current
        )
        if answer is None:
            return None
        path = _absolute(answer)
        problem = _video_problem(path)
        if problem is None:
            return path
        typer.echo(problem)


def _ask_dub(current: str) -> str:
    while True:
        answer = typer.prompt(
            "Preferred French dub when a film has both (VFF = France, VFQ = Quebec)",
            default=current,
        )
        if answer.strip().upper() in config.DUBS:
            return answer.strip().upper()
        typer.echo("Answer VFF or VFQ.")


def _claude_status() -> str:
    cli = claude.find_cli()
    if cli and claude.cli_logged_in(cli) is not False:
        return "Claude Code is installed and logged in: Claude can use your subscription."
    if os.environ.get("ANTHROPIC_API_KEY"):
        return "An API key is set (ANTHROPIC_API_KEY): Claude can use it."
    if cli:
        return "Claude Code is installed but not logged in (run: claude auth login)."
    return "Neither Claude Code nor an API key was found: the tool works without Claude."


def _ask_claude(backend: str, model: str) -> tuple[str, str]:
    typer.echo(
        "Claude can suggest each film's abbreviation and refine the cuts; "
        "without it, the tool uses simple rules."
    )
    typer.echo(_claude_status())
    if not typer.confirm("Use Claude when it is available?", default=backend != "off"):
        return "off", model
    model = typer.prompt("Claude model", default=model)
    return (backend if backend in ("cli", "api") else "auto"), model


def run_wizard(path: Path) -> None:
    """Asks the questions, then writes `path` (after a confirmation if it exists)."""
    values = _existing(path)
    defaults = {**config.DEFAULTS, **values}
    typer.echo(f"A few questions to set up {prog_name()} (Ctrl+C to stop, nothing is written).")
    typer.echo("Paths can be pasted or dragged here; [brackets] show what Enter keeps.\n")

    values["episodes_dir"] = _ask_episodes_dir(defaults.get("episodes_dir"))
    values["films_dir"] = _ask_films_dir(defaults.get("films_dir"))
    values["transition_sound"] = _ask_transition_sound(defaults.get("transition_sound"))
    values["transition_video"] = (
        _ask_transition_video(defaults.get("transition_video"))
        if values["transition_sound"] is not None
        else None
    )
    values["preferred_dub"] = _ask_dub(defaults["preferred_dub"])
    typer.echo("")
    backend = "off" if defaults.get("claude_enabled") is False else defaults["claude_backend"]
    values["claude_backend"], values["claude_model"] = _ask_claude(
        backend, defaults["claude_model"]
    )
    values["claude_enabled"] = True  # "off" is in the backend now

    typer.echo("")
    if path.exists() and not typer.confirm(f"Replace {path}?", default=True):
        typer.echo("Nothing was written.")
        raise typer.Exit(1)
    config.write_config(path, config.render_config(values))

    settings = config.load_settings(path)
    typer.echo(f"Configuration saved: {path}")
    for key, value in config.describe(settings):
        if "." not in key or key.startswith("claude."):
            typer.echo(f"  {key} = {value}")
    typer.echo("Other settings are in the file, commented. Change them there, or run init again.")
    typer.echo(f"\nNext: {prog_name()} run <notes file of a film>")
