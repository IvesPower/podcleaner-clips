"""Per-person configuration: a TOML file with French keys."""

import os
import tomllib
from dataclasses import dataclass, fields
from pathlib import Path
from typing import Any

from platformdirs import user_config_dir

from podcleaner_clips.errors import ClipsError

APP_NAME = "podcleaner-clips"
CONFIG_ENV_VAR = "PODCLEANER_CLIPS_CONFIG"
DUBS = ("VFF", "VFQ")


@dataclass(frozen=True)
class Settings:
    episodes_dir: Path
    films_dir: Path | None = None
    transition_sound: Path | None = None
    preferred_dub: str = "VFF"
    tolerance_s: float = 15.0
    use_subtitles: bool = True
    score_found: int = 70
    score_sure: int = 85
    sentence_gap_s: float = 0.6
    pad_before_s: float = 0.10
    pad_after_s: float = 0.25
    whisper_model: str = "large-v3-turbo"
    fade_s: float = 0.7
    lufs: float = -16.0
    true_peak: float = -1.0
    claude_enabled: bool = True
    claude_model: str = "claude-haiku-5-5"


# (TOML section, TOML key) → Settings field; section None = top level of the file.
_KEYS: dict[tuple[str | None, str], str] = {
    (None, "dossier_episodes"): "episodes_dir",
    (None, "dossier_films"): "films_dir",
    (None, "son_transition"): "transition_sound",
    (None, "doublage_prefere"): "preferred_dub",
    ("ajustement", "tolerance_s"): "tolerance_s",
    ("ajustement", "sous_titres"): "use_subtitles",
    ("ajustement", "score_trouve"): "score_found",
    ("ajustement", "score_sur"): "score_sure",
    ("ajustement", "pause_phrase_s"): "sentence_gap_s",
    ("ajustement", "marge_avant_s"): "pad_before_s",
    ("ajustement", "marge_apres_s"): "pad_after_s",
    ("ajustement", "modele_whisper"): "whisper_model",
    ("son", "fondu_s"): "fade_s",
    ("son", "lufs"): "lufs",
    ("son", "true_peak"): "true_peak",
    ("claude", "actif"): "claude_enabled",
    ("claude", "modele"): "claude_model",
}
_SECTIONS = {section for section, _ in _KEYS if section is not None}
_PATH_FIELDS = {"episodes_dir", "films_dir", "transition_sound"}
_FIELD_TYPES = {f.name: f.type for f in fields(Settings)}

_TEMPLATE = """\
# podcleaner-clips configuration.
# Paths may start with ~ (home folder); a relative path starts from this file's folder.
# Lines starting with # are ignored: remove the # to change a value (the value shown
# is the default).

# Folder where clips are stored, one subfolder per film (required).
# dossier_episodes = ""

# Folder to look for films in when the notes file only gives a file name.
# dossier_films = ""

# Sound played before and after each clip (required, unless --no-transition).
# son_transition = ""

# Preferred French dub when the film has both VFF (France) and VFQ (Quebec): "VFF" or "VFQ".
# doublage_prefere = "VFF"

[ajustement]
# Allowed gap (seconds) between a noted timecode and the chosen cut.
# tolerance_s = 15.0
# Look for the lines in the film's French subtitles first.
# sous_titres = true
# Similarity score (0-100) for a line to count as found, then as sure.
# score_trouve = 70
# score_sur = 85
# Silence (seconds) that marks the end of a sentence.
# pause_phrase_s = 0.6
# Margin (seconds) kept before the first word and after the last one.
# marge_avant_s = 0.10
# marge_apres_s = 0.25
# Whisper model used to transcribe the dub.
# modele_whisper = "large-v3-turbo"

[son]
# Length (seconds) of the fade-in and fade-out.
# fondu_s = 0.7
# Target loudness (integrated LUFS) and maximum true peak (dBTP).
# lufs = -16.0
# true_peak = -1.0

[claude]
# Ask Claude (abbreviation, cuts) when ANTHROPIC_API_KEY is set.
# actif = true
# modele = "claude-haiku-5-5"
"""


def default_config_path() -> Path:
    return Path(user_config_dir(APP_NAME, appauthor=False)) / "config.toml"


def resolve_config_path(path: Path | None = None) -> Path:
    """The argument, else PODCLEANER_CLIPS_CONFIG, else the user config directory."""
    if path is None:
        env = os.environ.get(CONFIG_ENV_VAR)
        path = Path(env) if env else default_config_path()
    return Path(path).expanduser()


def load_settings(path: Path | None = None) -> Settings:
    path = resolve_config_path(path)
    if not path.is_file():
        raise ClipsError(
            f"Configuration file not found: {path}\nCreate it with: podcleaner-clips config init"
        )
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8-sig"))
    except tomllib.TOMLDecodeError as exc:
        raise ClipsError(f"Cannot read configuration file ({path}): {exc}") from exc

    values: dict[str, Any] = {}
    for key, value in data.items():
        if isinstance(value, dict):
            if key not in _SECTIONS:
                raise ClipsError(f"Unknown section in {path}: [{key}]")
            for sub_key, sub_value in value.items():
                _set(values, path, key, sub_key, sub_value)
        else:
            _set(values, path, None, key, value)

    if "episodes_dir" not in values:
        raise ClipsError(f"Set dossier_episodes in {path}.")

    dub = values.get("preferred_dub", "VFF").upper()
    if dub not in DUBS:
        raise ClipsError(f'doublage_prefere must be "VFF" or "VFQ" ({path}).')
    values["preferred_dub"] = dub

    for name in _PATH_FIELDS & values.keys():
        p = Path(values[name]).expanduser()
        values[name] = p if p.is_absolute() else path.parent / p

    return Settings(**values)


def _set(values: dict[str, Any], path: Path, section: str | None, key: str, value: Any) -> None:
    field = _KEYS.get((section, key))
    if field is None:
        where = f"[{section}] " if section else ""
        raise ClipsError(f"Unknown key in {path}: {where}{key}")
    expected = _FIELD_TYPES[field]
    if expected is bool:
        ok = isinstance(value, bool)
    elif expected is int:
        ok = isinstance(value, int) and not isinstance(value, bool)
    elif expected is float:
        ok = isinstance(value, int | float) and not isinstance(value, bool)
        value = float(value) if ok else value
    else:  # text or path
        ok = isinstance(value, str)
    if not ok:
        raise ClipsError(f"Invalid value for {key} in {path}: {value!r}")
    values[field] = value


def write_template(path: Path) -> None:
    if path.exists():
        raise ClipsError(f"Configuration file already exists: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_TEMPLATE, encoding="utf-8")


def describe(settings: Settings) -> list[tuple[str, str]]:
    """(TOML key, display value) pairs, in file order."""
    rows = []
    for (section, key), field in _KEYS.items():
        value = getattr(settings, field)
        label = f"{section}.{key}" if section else key
        if value is None:
            text = "(none)"
        elif isinstance(value, bool):
            text = "true" if value else "false"
        else:
            text = str(value)
        rows.append((label, text))
    return rows
