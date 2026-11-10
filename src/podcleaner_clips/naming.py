"""Timecodes and names: pure functions, no disk access."""

import re
import unicodedata

# HH:MM:SS, or MM:SS (1 to 3 minute digits), with 1 to 3 optional decimals.
_TC = re.compile(r"(?:(\d{1,2}):([0-5]\d)|(\d{1,3})):([0-5]\d)(?:[.,](\d{1,3}))?")
_FOLDER_MAX = 60
# "25 min 30", "25min30", "25 min 30 s", "25 min" → MM:SS.
_MIN_SEC = re.compile(r"(\d{1,3})\s*min(?:\s*(\d{1,2})(?:\s*s)?)?", re.IGNORECASE)


def _normalize_tc(text: str) -> str:
    """Fixes common typing: `;` instead of `:`, minutes written out with "min"."""
    text = text.strip().replace(";", ":")
    match = _MIN_SEC.fullmatch(text)
    if match:
        minutes, seconds = match.groups()
        return f"{minutes}:{int(seconds or 0):02d}"
    return text


_LIGATURES = str.maketrans({"œ": "oe", "Œ": "OE", "æ": "ae", "Æ": "AE", "ß": "ss"})
_WORD = re.compile(r"[A-Za-z0-9]+")
_ARTICLES = {"le", "la", "les", "l", "un", "une", "des", "the", "a", "an"}
# A year in parentheses: "(2015)".
_YEAR = re.compile(r"\(\s*(?:19|20)\d\d\s*\)")
_WINDOWS_RESERVED = {"CON", "PRN", "AUX", "NUL"} | {
    f"{p}{i}" for p in ("COM", "LPT") for i in range(1, 10)
}


def parse_tc(text: str) -> float:
    """`HH:MM:SS` or `MM:SS` (45:12 = 45 min 12 s), decimals after `.` or `,`; in seconds."""
    match = _TC.fullmatch(_normalize_tc(text))
    if not match:
        raise ValueError(f"Timecode invalide : {text!r} (attendu HH:MM:SS ou MM:SS)")
    hours, minutes, short_minutes, seconds, fraction = match.groups()
    if short_minutes is not None:
        hours, minutes = "0", short_minutes
    total = int(hours) * 3600 + int(minutes) * 60 + int(seconds)
    if fraction:
        total += float(f"0.{fraction}")
    return round(total, 3)


def format_tc(seconds: float) -> str:
    """Seconds → `HH:MM:SS.mmm`."""
    if seconds < 0:
        raise ValueError(f"Negative duration: {seconds}")
    hours, rest = divmod(round(seconds * 1000), 3_600_000)
    minutes, rest = divmod(rest, 60_000)
    secs, millis = divmod(rest, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}.{millis:03d}"


def strip_accents(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text.translate(_LIGATURES))
    return "".join(c for c in decomposed if not unicodedata.combining(c))


def _words(text: str) -> list[str]:
    return _WORD.findall(strip_accents(text))


def slugify(text: str, max_len: int = 40) -> str:
    """Whole lowercase ASCII words joined by `-`, at most `max_len` characters."""
    words = [w.lower() for w in _words(text)]
    if not words:
        return "extrait"
    slug = words[0][:max_len]
    for word in words[1:]:
        if len(slug) + 1 + len(word) > max_len:
            break
        slug = f"{slug}-{word}"
    return slug


def fallback_abbreviation(title: str) -> str:
    """Title initials without the leading article, 2 to 6 characters ("Le Dîner de cons" → DDC)."""
    words = _words(_YEAR.sub(" ", title))
    if len(words) > 1 and words[0].lower() in _ARTICLES:
        words = words[1:]
    if len(words) == 1:
        abbr = words[0][:2]
    else:
        abbr = "".join(w[0] for w in words)[:6]
    return abbr.upper() if len(abbr) >= 2 else "FILM"


def title_from_film(file_name: str) -> str:
    """Film title from its file name: up to the year in parentheses, else the name alone.

    "The Night Before (2015) Bluray-1080p.mkv" → "The Night Before (2015)".
    """
    stem = file_name.rsplit(".", 1)[0] if "." in file_name else file_name
    year = _YEAR.search(stem)
    return (stem[: year.end()] if year else stem).strip()


def film_folder_name(title: str) -> str:
    """Film title usable as a folder name on macOS and Windows (≤ 60 characters)."""
    ascii_only = "".join(
        c if c.isascii() and c.isprintable() and c not in '<>:"/\\|?*' else " "
        for c in strip_accents(title)
    )
    words = ascii_only.split()
    name = words[0][:_FOLDER_MAX] if words else ""
    for word in words[1:]:
        if len(name) + 1 + len(word) > _FOLDER_MAX:
            break
        name = f"{name} {word}"
    name = name.rstrip(". ")
    if not name:
        return "Film"
    if name.upper() in _WINDOWS_RESERVED:
        name += "_"
    return name


def clip_basename(abbr: str, number: int, line: str) -> str:
    """`{abbreviation}-{2-digit number}-{reference slug}`, without extension."""
    return f"{abbr}-{number:02d}-{slugify(line)}"
