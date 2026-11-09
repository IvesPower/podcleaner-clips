"""Lecture du fichier de notes pris pendant le visionnage.

Une ligne d'extrait commence et finit par un timecode : `27:15 ce bébé c'est une connerie 27:37`.
L'ancienne forme `- 00:12:34 > 00:12:51 | réplique` reste acceptée. Toute autre ligne est ignorée.
"""

import codecs
import re
from dataclasses import dataclass
from pathlib import Path

from podcleaner_clips.errors import ClipsError
from podcleaner_clips.naming import format_tc, parse_tc

_BULLET = re.compile(r"^[-*]\s+")
_LEGACY = re.compile(r"(?P<start>[^>|]+?)\s*>\s*(?P<end>[^>|]+?)\s*\|\s*(?P<ref>.*)")
_HEADER_KEY = re.compile(r"(?P<key>fichier|abr[eé]viation)\s*:\s*(?P<value>.*)", re.IGNORECASE)
_LEADING_SEPARATOR = re.compile(r"^[:\-–—]+\s*")
_FRAGMENT_SEPARATOR = re.compile(r"…|\.\.\.|\s[-–—]\s")
_MAX_TC_TOKENS = 3  # « 25 min 30 »


@dataclass(frozen=True)
class ClipNote:
    number: int
    start: float
    end: float
    reference: str
    fragments: list[str]
    source_line: int


@dataclass(frozen=True)
class Notes:
    title: str | None
    film_file: str | None
    abbreviation: str | None
    clips: list[ClipNote]
    errors: list[str]


def split_fragments(reference: str) -> list[str]:
    """Découpe une référence sur `…`, `...` et ` - ` (pas le tiret de « peut-être »)."""
    pieces = [p.strip() for p in _FRAGMENT_SEPARATOR.split(reference)]
    return [p for p in pieces if p] or [reference.strip()]


def _try_tc(text: str) -> float | None:
    try:
        return parse_tc(text)
    except ValueError:
        return None


def _parse_clip_line(line: str) -> tuple[float, float, str] | None:
    """(début, fin, référence) si la ligne est une ligne d'extrait, sinon None."""
    text = _BULLET.sub("", line.strip())
    legacy = _LEGACY.fullmatch(text)
    if legacy:
        start, end = _try_tc(legacy["start"]), _try_tc(legacy["end"])
        if start is not None and end is not None:
            return start, end, legacy["ref"].strip()

    tokens = text.split()
    for n_start in range(_MAX_TC_TOKENS, 0, -1):
        if n_start >= len(tokens):
            continue
        start = _try_tc(" ".join(tokens[:n_start]))
        if start is None:
            continue
        for n_end in range(_MAX_TC_TOKENS, 0, -1):
            if n_start + n_end > len(tokens):
                continue
            end = _try_tc(" ".join(tokens[-n_end:]))
            if end is not None:
                middle = " ".join(tokens[n_start : len(tokens) - n_end])
                return start, end, _LEADING_SEPARATOR.sub("", middle).strip()
        return None
    return None


def read_notes(path: Path) -> Notes:
    if not path.is_file():
        raise ClipsError(f"Fichier de notes introuvable : {path}")
    lines = path.read_text(encoding="utf-8-sig").splitlines()

    title = film_file = abbreviation = None
    clips: list[ClipNote] = []
    errors: list[str] = []
    number = 0
    for line_no, line in enumerate(lines, start=1):
        parsed = _parse_clip_line(line)
        if parsed is None:
            if number == 0:
                stripped = line.strip()
                header = _HEADER_KEY.fullmatch(stripped)
                if stripped.startswith("# ") and title is None:
                    title = stripped[2:].strip() or None
                elif header and header["key"].lower() == "fichier":
                    film_file = header["value"].strip() or None
                elif header:
                    abbreviation = header["value"].strip().upper() or None
            continue

        number += 1
        start, end, reference = parsed
        if not reference:
            errors.append(f"Ligne {line_no} : aucune référence entre les deux timecodes")
        elif start >= end:
            errors.append(
                f"Ligne {line_no} : le début {format_tc(start)} n'est pas avant la fin "
                f"{format_tc(end)}"
            )
        else:
            clips.append(
                ClipNote(number, start, end, reference, split_fragments(reference), line_no)
            )
    return Notes(title, film_file, abbreviation, clips, errors)


def write_abbreviation(path: Path, abbr: str) -> None:
    """Écrit ou remplace `abreviation:` dans l'en-tête, sans toucher au reste du fichier."""
    data = path.read_bytes()
    bom = data.startswith(codecs.BOM_UTF8)
    lines = data.decode("utf-8-sig").splitlines(keepends=True)
    newline = "\r\n" if lines and lines[0].endswith("\r\n") else "\n"

    insert_at = 0
    replaced = False
    for i, line in enumerate(lines):
        if _parse_clip_line(line) is not None:
            break
        stripped = line.strip()
        header = _HEADER_KEY.fullmatch(stripped)
        if header and header["key"].lower() != "fichier":
            key = stripped.split(":", 1)[0]
            ending = line[len(line.rstrip("\r\n")) :]
            lines[i] = f"{key}: {abbr}{ending}"
            replaced = True
            break
        if header or (stripped.startswith("# ") and insert_at == 0):
            insert_at = i + 1
    if not replaced:
        if insert_at and not lines[insert_at - 1].endswith(("\n", "\r")):
            lines[insert_at - 1] += newline
        lines.insert(insert_at, f"abreviation: {abbr}{newline}")

    text = "".join(lines)
    path.write_bytes((codecs.BOM_UTF8 if bom else b"") + text.encode("utf-8"))
