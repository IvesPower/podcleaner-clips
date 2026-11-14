"""The pixel-art title shown when the tool starts in a terminal."""

import os
import shutil
import sys

import click
from rich.console import Console
from rich.text import Text

from podcleaner_clips import __version__

NAME = "podcleaner-clips"
TAGLINE = "cut the clips noted while watching"
NO_BANNER_ENV_VAR = "PODCLEANER_CLIPS_NO_BANNER"

# 3×5 pixel letters ("#" = lit). Two pixel rows make one text line, with half blocks.
_FONT = {
    "p": ("###", "#.#", "###", "#..", "#.."),
    "o": ("###", "#.#", "#.#", "#.#", "###"),
    "d": ("##.", "#.#", "#.#", "#.#", "##."),
    "c": ("###", "#..", "#..", "#..", "###"),
    "l": ("#..", "#..", "#..", "#..", "###"),
    "e": ("###", "#..", "##.", "#..", "###"),
    "a": ("###", "#.#", "###", "#.#", "#.#"),
    "n": ("##.", "#.#", "#.#", "#.#", "#.#"),
    "r": ("##.", "#.#", "##.", "#.#", "#.#"),
    "-": ("...", "...", "###", "...", "..."),
    "i": ("###", ".#.", ".#.", ".#.", "###"),
    "s": ("###", "#..", "###", "..#", "###"),
}
_HALF_BLOCKS = {(True, True): "█", (True, False): "▀", (False, True): "▄", (False, False): " "}
# Gradient from the first column to the last (cyan → violet → pink).
_GRADIENT = ((0, 200, 255), (140, 90, 255), (255, 80, 170))


def pixel_lines(text: str = NAME) -> list[str]:
    """`text` drawn with the pixel font: 3 lines of half blocks."""
    rows = ["." + ".".join(_FONT[ch][r] for ch in text) for r in range(5)]
    rows.append("." * len(rows[0]))  # even number of pixel rows
    return [
        "".join(_HALF_BLOCKS[(top == "#", bottom == "#")] for top, bottom in zip(t, b, strict=True))
        for t, b in zip(rows[::2], rows[1::2], strict=True)
    ]


def _colour(position: float) -> str:
    """Hex colour at `position` (0 to 1) along the gradient."""
    segments = len(_GRADIENT) - 1
    i = min(int(position * segments), segments - 1)
    local = position * segments - i
    start, end = _GRADIENT[i], _GRADIENT[i + 1]
    r, g, b = (round(a + (z - a) * local) for a, z in zip(start, end, strict=True))
    return f"#{r:02x}{g:02x}{b:02x}"


def _stdout_is_tty() -> bool:
    return sys.stdout.isatty()


def _can_print(characters: str) -> bool:
    try:
        characters.encode(sys.stdout.encoding or "ascii")
    except (UnicodeEncodeError, LookupError):
        return False
    return True


def wanted(ctx: click.Context | None) -> bool:
    """False when the output is not a terminal, or the banner is turned off (`--no-banner`)."""
    if not _stdout_is_tty() or os.environ.get(NO_BANNER_ENV_VAR):
        return False
    return not (ctx is not None and ctx.find_root().params.get("no_banner"))


def show(ctx: click.Context | None) -> None:
    """Prints the title, or a one-line one when the terminal is too narrow or cannot draw it."""
    if not wanted(ctx):
        return
    console = Console(file=sys.stdout, highlight=False)
    lines = pixel_lines()
    width = len(lines[0])
    if shutil.get_terminal_size().columns < width or not _can_print("█▀▄·"):
        console.print(f"[bold]{NAME}[/bold] {__version__} - {TAGLINE}")
        console.print()
        return
    for line in lines:
        text = Text()
        for column, char in enumerate(line):
            text.append(char, style=_colour(column / max(width - 1, 1)))
        console.print(text)
    console.print(Text(f" v{__version__} · {TAGLINE}", style="dim"))
    console.print()
