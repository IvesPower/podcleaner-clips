"""Per-person configuration: a TOML file (French keys of version 0.1.0 are still read)."""

import os
import re
import tomllib
from dataclasses import MISSING, asdict, dataclass, field, fields
from pathlib import Path
from typing import Any

from platformdirs import user_config_dir

from podcleaner_clips import prog_name
from podcleaner_clips.errors import ClipsError

APP_NAME = "podcleaner-clips"
CONFIG_ENV_VAR = "PODCLEANER_CLIPS_CONFIG"
DUBS = ("VFF", "VFQ")
CLAUDE_BACKENDS = ("auto", "cli", "api", "off")
# Loudness targets ffmpeg's loudnorm accepts (integrated LUFS).
LUFS_MIN, LUFS_MAX = -70.0, -5.0


def check_lufs(value: float) -> bool:
    return LUFS_MIN <= value <= LUFS_MAX


@dataclass(frozen=True)
class Settings:
    episodes_dir: Path
    films_dir: Path | None = None
    transition_sound: Path | None = None
    transition_video: Path | None = None
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
    transition_lufs: float = -22.0
    true_peak: float = -1.0
    claude_enabled: bool = True  # false = backend "off" (kept for older files)
    claude_backend: str = "auto"
    claude_model: str = "claude-sonnet-5-5"
    # Not settings: what to tell the user about the file (old key names, …).
    notices: tuple[str, ...] = field(default=(), compare=False)


# (TOML section, TOML key) → Settings field; section None = top level of the file.
_KEYS: dict[tuple[str | None, str], str] = {
    (None, "episodes_dir"): "episodes_dir",
    (None, "films_dir"): "films_dir",
    (None, "transition_sound"): "transition_sound",
    (None, "transition_video"): "transition_video",
    (None, "preferred_dub"): "preferred_dub",
    ("adjust", "tolerance_s"): "tolerance_s",
    ("adjust", "use_subtitles"): "use_subtitles",
    ("adjust", "score_found"): "score_found",
    ("adjust", "score_sure"): "score_sure",
    ("adjust", "sentence_gap_s"): "sentence_gap_s",
    ("adjust", "pad_before_s"): "pad_before_s",
    ("adjust", "pad_after_s"): "pad_after_s",
    ("adjust", "whisper_model"): "whisper_model",
    ("audio", "fade_s"): "fade_s",
    ("audio", "lufs"): "lufs",
    ("audio", "transition_lufs"): "transition_lufs",
    ("audio", "true_peak"): "true_peak",
    ("claude", "backend"): "claude_backend",
    ("claude", "enabled"): "claude_enabled",
    ("claude", "model"): "claude_model",
}
# Keys of version 0.1.0 (French), still read: (section, key) → current (section, key).
_LEGACY_SECTIONS = {"ajustement": "adjust", "son": "audio"}
_LEGACY_KEYS: dict[tuple[str | None, str], tuple[str | None, str]] = {
    (None, "dossier_episodes"): (None, "episodes_dir"),
    (None, "dossier_films"): (None, "films_dir"),
    (None, "son_transition"): (None, "transition_sound"),
    (None, "doublage_prefere"): (None, "preferred_dub"),
    ("ajustement", "tolerance_s"): ("adjust", "tolerance_s"),
    ("ajustement", "sous_titres"): ("adjust", "use_subtitles"),
    ("ajustement", "score_trouve"): ("adjust", "score_found"),
    ("ajustement", "score_sur"): ("adjust", "score_sure"),
    ("ajustement", "pause_phrase_s"): ("adjust", "sentence_gap_s"),
    ("ajustement", "marge_avant_s"): ("adjust", "pad_before_s"),
    ("ajustement", "marge_apres_s"): ("adjust", "pad_after_s"),
    ("ajustement", "modele_whisper"): ("adjust", "whisper_model"),
    ("son", "fondu_s"): ("audio", "fade_s"),
    ("son", "lufs"): ("audio", "lufs"),
    ("son", "true_peak"): ("audio", "true_peak"),
    ("claude", "actif"): ("claude", "enabled"),
    ("claude", "modele"): ("claude", "model"),
}
_SECTIONS = {section for section, _ in _KEYS if section is not None}
_PATH_FIELDS = {"episodes_dir", "films_dir", "transition_sound", "transition_video"}
_FIELD_TYPES = {f.name: f.type for f in fields(Settings)}

_TEMPLATE = """\
# podcleaner-clips configuration.
# Paths may start with ~ (home folder); a relative path starts from this file's folder.
# On Windows, write paths with / ("C:/Films") or between single quotes ('C:\\Films'):
# a \\ between double quotes is read as an escape sequence.
# Lines starting with # are ignored: remove the # to change a value (the value shown
# is the default).

# Folder where clips are stored, one subfolder per film (required).
# episodes_dir = ""

# Folder to look for films in when the notes file only gives a file name.
# films_dir = ""

# Sound played before and after each clip (required, unless --no-transition).
# transition_sound = ""

# Video shown during the transition sound instead of a black screen (optional; its own
# sound is not used). Cut or looped to the right length, fitted to the film's picture.
# transition_video = ""

# Preferred French dub when the film has both VFF (France) and VFQ (Quebec): "VFF" or "VFQ".
# preferred_dub = "VFF"

[adjust]
# Allowed gap (seconds) between a noted timecode and the chosen cut.
# tolerance_s = 15.0
# Look for the lines in the film's French subtitles first.
# use_subtitles = true
# Similarity score (0-100) for a line to count as found, then as sure.
# score_found = 70
# score_sure = 85
# Silence (seconds) that marks the end of a sentence.
# sentence_gap_s = 0.6
# Margin (seconds) kept before the first word and after the last one.
# pad_before_s = 0.10
# pad_after_s = 0.25
# Whisper model used to transcribe the dub.
# whisper_model = "large-v3-turbo"

[audio]
# Length (seconds) of the fade-in and fade-out.
# fade_s = 0.7
# Loudness (integrated LUFS, from -70 to -5) of the film sound of each clip, and of the
# transition sound; the clip never goes over the true peak (dBTP). Also --lufs and
# --transition-lufs on the command line.
# lufs = -16.0
# transition_lufs = -22.0
# true_peak = -1.0

[claude]
# Who answers when the tool asks Claude (abbreviation, cuts):
#   "auto": the Claude Code CLI if it is installed and logged in (your Claude
#           subscription), else the API if ANTHROPIC_API_KEY is set, else no Claude;
#   "cli":  only the Claude Code CLI;  "api": only the API;  "off": never.
# backend = "auto"
# Model that picks the cuts: Sonnet weighs the humour and the context of a line well;
# "claude-haiku-5-5" is faster and cheaper, "claude-opus-5-5" the most careful.
# model = "claude-sonnet-5-5"
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
            f"Configuration file not found: {path}\nCreate it with: {prog_name()} init"
        )
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8-sig"))
    except tomllib.TOMLDecodeError as exc:
        raise ClipsError(f"Cannot read configuration file ({path}): {exc}") from exc

    values: dict[str, Any] = {}
    legacy: list[str] = []
    for key, value in data.items():
        if isinstance(value, dict):
            if key not in _SECTIONS and key not in _LEGACY_SECTIONS:
                raise ClipsError(f"Unknown section in {path}: [{key}]")
            for sub_key, sub_value in value.items():
                _set(values, legacy, path, key, sub_key, sub_value)
        else:
            _set(values, legacy, path, None, key, value)

    if "episodes_dir" not in values:
        raise ClipsError(f"Set episodes_dir in {path}.")

    dub = values.get("preferred_dub", "VFF").upper()
    if dub not in DUBS:
        raise ClipsError(f'preferred_dub must be "VFF" or "VFQ" ({path}).')
    values["preferred_dub"] = dub

    backend = values.get("claude_backend", "auto").lower()
    if backend not in CLAUDE_BACKENDS:
        choices = ", ".join(f'"{b}"' for b in CLAUDE_BACKENDS)
        raise ClipsError(f"[claude] backend must be one of {choices} ({path}).")
    if values.get("claude_enabled") is False:
        backend = "off"
    values["claude_backend"] = backend

    for name, key in (("lufs", "lufs"), ("transition_lufs", "transition_lufs")):
        if name in values and not check_lufs(values[name]):
            raise ClipsError(
                f"[audio] {key} must be between {LUFS_MIN:g} and {LUFS_MAX:g} ({path})."
            )

    for name in _PATH_FIELDS & values.keys():
        p = Path(values[name]).expanduser()
        values[name] = p if p.is_absolute() else path.parent / p

    notices = ()
    if legacy:
        notices = (
            f"{path} uses old French key names; rename them: " + ", ".join(dict.fromkeys(legacy)),
        )
    return Settings(**values, notices=notices)


def _label(section: str | None, key: str) -> str:
    return f"[{section}] {key}" if section else key


def _set(
    values: dict[str, Any],
    legacy: list[str],
    path: Path,
    section: str | None,
    key: str,
    value: Any,
) -> None:
    current = _LEGACY_KEYS.get((section, key))
    if current is not None:
        legacy.append(f"{_label(section, key)} → {_label(*current)}")
        section, key = current
    elif section in _LEGACY_SECTIONS:
        legacy.append(f"[{section}] → [{_LEGACY_SECTIONS[section]}]")
        section = _LEGACY_SECTIONS[section]
    name = _KEYS.get((section, key))
    if name is None:
        raise ClipsError(f"Unknown key in {path}: {_label(section, key)}")
    if name in values:
        raise ClipsError(f"{_label(section, key)} is set twice in {path} (old and new name).")
    expected = _FIELD_TYPES[name]
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
        raise ClipsError(f"Invalid value for {_label(section, key)} in {path}: {value!r}")
    values[name] = value


_COMMENTED_KEY = re.compile(r"^# (?P<key>\w+) = ")
_SECTION_LINE = re.compile(r"^\[(?P<section>\w+)\]$")
DEFAULTS = {f.name: f.default for f in fields(Settings) if f.default is not MISSING}


def _toml_value(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int | float):
        return repr(value)
    text = str(value)
    if "'" not in text and "\n" not in text:
        return f"'{text}'"  # literal string: a Windows \ stays a \
    escaped = text.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
    return f'"{escaped}"'


def settings_values(settings: Settings) -> dict[str, Any]:
    """The settings as {field: value}, ready for `render_config`."""
    values = asdict(settings)
    values.pop("notices")
    return values


def render_config(values: dict[str, Any]) -> str:
    """The commented template with every given value that is not the default filled in."""
    if values.get("claude_enabled") is False:
        values = {**values, "claude_backend": "off"}
    lines = []
    section = None
    for line in _TEMPLATE.splitlines():
        header = _SECTION_LINE.match(line)
        if header:
            section = header["section"]
        commented = _COMMENTED_KEY.match(line)
        if commented:
            name = _KEYS.get((section, commented["key"]))
            value = values.get(name) if name else None
            if value is not None and (name not in DEFAULTS or value != DEFAULTS[name]):
                line = f"{commented['key']} = {_toml_value(value)}"
        lines.append(line)
    return "\n".join(lines) + "\n"


def write_config(path: Path, text: str) -> None:
    """Writes next to the target first, then renames: an interrupted write leaves no half file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    part = path.with_name(f".{path.name}.part")
    try:
        part.write_text(text, encoding="utf-8")
        os.replace(part, path)
    finally:
        part.unlink(missing_ok=True)


def write_template(path: Path) -> None:
    if path.exists():
        raise ClipsError(f"Configuration file already exists: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_TEMPLATE, encoding="utf-8")


def describe(settings: Settings) -> list[tuple[str, str]]:
    """(TOML key, display value) pairs, in file order."""
    rows = []
    for (section, key), name in _KEYS.items():
        if name == "claude_enabled":  # older switch, shown through backend
            continue
        value = getattr(settings, name)
        label = f"{section}.{key}" if section else key
        if value is None:
            text = "(none)"
        elif isinstance(value, bool):
            text = "true" if value else "false"
        else:
            text = str(value)
        rows.append((label, text))
    return rows
