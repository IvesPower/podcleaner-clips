"""Podcleaner-clips: cut the movie clips noted while watching."""

import sys
from pathlib import PureWindowsPath

__version__ = "0.1.0"

COMMAND_NAMES = ("podcleaner-clips", "pclips")


def prog_name() -> str:
    """The command name as typed (`pclips` or `podcleaner-clips`), for help and messages."""
    # PureWindowsPath splits on / and \, so pclips.exe on Windows is read the same way.
    name = PureWindowsPath(sys.argv[0]).stem if sys.argv and sys.argv[0] else ""
    return name if name in COMMAND_NAMES else COMMAND_NAMES[0]
