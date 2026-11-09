"""Configuration par personne : un fichier TOML, clés en français."""

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


# (section TOML, clé TOML) → champ de Settings ; section None = racine du fichier.
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
# Configuration de podcleaner-clips.
# Les chemins peuvent commencer par ~ (dossier personnel) ; un chemin relatif part du
# dossier de ce fichier. Les lignes commençant par # sont ignorées : retirez le # pour
# changer une valeur (celle indiquée est la valeur par défaut).

# Dossier où sont rangés les extraits, un sous-dossier par film (obligatoire).
# dossier_episodes = ""

# Dossier où chercher les films quand le fichier de notes ne donne qu'un nom de fichier.
# dossier_films = ""

# Son joué avant et après chaque extrait (obligatoire, sauf avec --no-transition).
# son_transition = ""

# Doublage préféré quand le film a une VFF et une VFQ : "VFF" ou "VFQ".
# doublage_prefere = "VFF"

[ajustement]
# Écart admis (secondes) entre un timecode noté et la borne retenue.
# tolerance_s = 15.0
# Chercher d'abord les répliques dans les sous-titres français du film.
# sous_titres = true
# Score de ressemblance (0-100) pour qu'une réplique soit trouvée, puis jugée sûre.
# score_trouve = 70
# score_sur = 85
# Silence (secondes) qui marque une fin de phrase.
# pause_phrase_s = 0.6
# Marge (secondes) gardée avant le premier mot et après le dernier.
# marge_avant_s = 0.10
# marge_apres_s = 0.25
# Modèle Whisper utilisé pour transcrire le doublage.
# modele_whisper = "large-v3-turbo"

[son]
# Durée (secondes) des fondus d'ouverture et de fermeture.
# fondu_s = 0.7
# Volume visé (LUFS intégré) et crête maximale (dBTP).
# lufs = -16.0
# true_peak = -1.0

[claude]
# Demander l'avis de Claude (abréviation, bornes) quand ANTHROPIC_API_KEY est définie.
# actif = true
# modele = "claude-haiku-5-5"
"""


def default_config_path() -> Path:
    return Path(user_config_dir(APP_NAME, appauthor=False)) / "config.toml"


def resolve_config_path(path: Path | None = None) -> Path:
    """Argument, sinon PODCLEANER_CLIPS_CONFIG, sinon le dossier de configuration utilisateur."""
    if path is None:
        env = os.environ.get(CONFIG_ENV_VAR)
        path = Path(env) if env else default_config_path()
    return Path(path).expanduser()


def load_settings(path: Path | None = None) -> Settings:
    path = resolve_config_path(path)
    if not path.is_file():
        raise ClipsError(
            f"Fichier de configuration introuvable : {path}\n"
            "Créez-le avec : podcleaner-clips config init"
        )
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8-sig"))
    except tomllib.TOMLDecodeError as exc:
        raise ClipsError(f"Fichier de configuration illisible ({path}) : {exc}") from exc

    values: dict[str, Any] = {}
    for key, value in data.items():
        if isinstance(value, dict):
            if key not in _SECTIONS:
                raise ClipsError(f"Section inconnue dans {path} : [{key}]")
            for sub_key, sub_value in value.items():
                _set(values, path, key, sub_key, sub_value)
        else:
            _set(values, path, None, key, value)

    if "episodes_dir" not in values:
        raise ClipsError(f"Indiquez dossier_episodes dans {path}.")

    dub = values.get("preferred_dub", "VFF").upper()
    if dub not in DUBS:
        raise ClipsError(f'doublage_prefere doit valoir "VFF" ou "VFQ" ({path}).')
    values["preferred_dub"] = dub

    for name in _PATH_FIELDS & values.keys():
        p = Path(values[name]).expanduser()
        values[name] = p if p.is_absolute() else path.parent / p

    return Settings(**values)


def _set(values: dict[str, Any], path: Path, section: str | None, key: str, value: Any) -> None:
    field = _KEYS.get((section, key))
    if field is None:
        where = f"[{section}] " if section else ""
        raise ClipsError(f"Clé inconnue dans {path} : {where}{key}")
    expected = _FIELD_TYPES[field]
    if expected is bool:
        ok = isinstance(value, bool)
    elif expected is int:
        ok = isinstance(value, int) and not isinstance(value, bool)
    elif expected is float:
        ok = isinstance(value, int | float) and not isinstance(value, bool)
        value = float(value) if ok else value
    else:  # texte ou chemin
        ok = isinstance(value, str)
    if not ok:
        raise ClipsError(f"Valeur invalide pour {key} dans {path} : {value!r}")
    values[field] = value


def write_template(path: Path) -> None:
    if path.exists():
        raise ClipsError(f"Le fichier de configuration existe déjà : {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_TEMPLATE, encoding="utf-8")


def describe(settings: Settings) -> list[tuple[str, str]]:
    """Paires (clé TOML, valeur affichable), dans l'ordre du fichier."""
    rows = []
    for (section, key), field in _KEYS.items():
        value = getattr(settings, field)
        label = f"{section}.{key}" if section else key
        if value is None:
            text = "(aucun)"
        elif isinstance(value, bool):
            text = "true" if value else "false"
        else:
            text = str(value)
        rows.append((label, text))
    return rows
