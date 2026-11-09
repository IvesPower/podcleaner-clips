"""Timecodes et noms : fonctions pures, sans accès au disque."""

import re
import unicodedata

# HH:MM:SS, ou MM:SS (minutes sur 1 à 3 chiffres), avec 1 à 3 décimales facultatives.
_TC = re.compile(r"(?:(\d{1,2}):([0-5]\d)|(\d{1,3})):([0-5]\d)(?:[.,](\d{1,3}))?")
_FOLDER_MAX = 60
# « 25 min 30 », « 25min30 », « 25 min 30 s », « 25 min » → MM:SS.
_MIN_SEC = re.compile(r"(\d{1,3})\s*min(?:\s*(\d{1,2})(?:\s*s)?)?", re.IGNORECASE)


def _normalize_tc(text: str) -> str:
    """Corrige les saisies courantes : `;` à la place de `:`, minutes écrites en toutes lettres."""
    text = text.strip().replace(";", ":")
    match = _MIN_SEC.fullmatch(text)
    if match:
        minutes, seconds = match.groups()
        return f"{minutes}:{int(seconds or 0):02d}"
    return text


_LIGATURES = str.maketrans({"œ": "oe", "Œ": "OE", "æ": "ae", "Æ": "AE", "ß": "ss"})
_WORD = re.compile(r"[A-Za-z0-9]+")
_ARTICLES = {"le", "la", "les", "l", "un", "une", "des", "the", "a", "an"}
_WINDOWS_RESERVED = {"CON", "PRN", "AUX", "NUL"} | {
    f"{p}{i}" for p in ("COM", "LPT") for i in range(1, 10)
}


def parse_tc(text: str) -> float:
    """`HH:MM:SS` ou `MM:SS` (45:12 = 45 min 12 s), décimales après `.` ou `,` ; en secondes."""
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
    """Secondes → `HH:MM:SS.mmm`."""
    if seconds < 0:
        raise ValueError(f"Durée négative : {seconds}")
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
    """Mots entiers en minuscules ASCII joints par `-`, au plus `max_len` caractères."""
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
    """Initiales du titre sans l'article initial, 2 à 6 caractères (« Le Dîner de cons » → DDC)."""
    words = _words(title)
    if len(words) > 1 and words[0].lower() in _ARTICLES:
        words = words[1:]
    if len(words) == 1:
        abbr = words[0][:2]
    else:
        abbr = "".join(w[0] for w in words)[:6]
    return abbr.upper() if len(abbr) >= 2 else "FILM"


def film_folder_name(title: str) -> str:
    """Titre du film utilisable comme nom de dossier sur macOS et Windows (≤ 60 caractères)."""
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
    """`{abréviation}-{numéro sur 2 chiffres}-{slug de la réplique}`, sans extension."""
    return f"{abbr}-{number:02d}-{slugify(line)}"
