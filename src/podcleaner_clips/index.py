"""The film's extraits.json index: chosen cuts, Claude's opinions, and what a rerun must redo."""

import hashlib
import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from podcleaner_clips.adjust import Cut
from podcleaner_clips.claude import ClaudeAdvice
from podcleaner_clips.errors import ClipsError
from podcleaner_clips.media import AudioTrack
from podcleaner_clips.naming import format_tc, parse_tc
from podcleaner_clips.notes import ClipNote

INDEX_NAME = "extraits.json"
INDEX_VERSION = 1
OUTPUT_KINDS = ("audio", "video")

# Action kinds, shown as is in the summary.
NEW, CHANGED, UNCHANGED, RENAMED, MISSING = "nouveau", "modifie", "inchange", "renomme", "manquant"


def fingerprint(
    note: ClipNote,
    *,
    adjust: bool,
    transition: bool,
    track: int,
    transition_sha: str | None,
    render: dict,
) -> str:
    """Everything that changes a clip's files, except its number (so a moved line is renamed)."""
    data = {
        "start": round(note.start, 3),
        "end": round(note.end, 3),
        "reference": note.reference,
        "adjust": adjust,
        "transition": transition,
        "track": track,
        "transition_sha": transition_sha,
        "render": render,
    }
    text = json.dumps(data, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


@dataclass
class ClipEntry:
    """One clip as rendered; `files` maps "audio"/"video" to paths relative to the film folder."""

    number: int
    reference: str
    found_fragments: list[str]
    fingerprint: str
    noted_start: float
    noted_end: float
    cut: Cut
    claude_advice: ClaudeAdvice | None
    duration_s: float
    files: dict[str, str] = field(default_factory=dict)


@dataclass
class FilmIndex:
    title: str
    abbreviation: str
    film_file: str
    audio_track: AudioTrack | None
    claude_advice: list[ClaudeAdvice]
    clips: list[ClipEntry]


@dataclass(frozen=True)
class Action:
    """What a run does for one clip.

    `reuse`: the previous entry whose cut is kept (unchanged, renamed, missing file).
    `rename_from`: existing files to move to the clip's new name (renamed clips).
    """

    number: int
    kind: str
    reuse: ClipEntry | None = None
    rename_from: dict[str, Path] = field(default_factory=dict)


def _has_files(entry: ClipEntry, out_dir: Path, wanted: set[str]) -> bool:
    return all(k in entry.files and (out_dir / entry.files[k]).is_file() for k in wanted)


def plan_actions(
    notes: list[ClipNote],
    fingerprints: dict[int, str],
    previous: FilmIndex | None,
    out_dir: Path,
    wanted: set[str],
) -> tuple[list[Action], list[Path]]:
    """One action per clip of the notes, and the files of previous clips no longer noted."""
    old = list(previous.clips) if previous else []
    unused = set(range(len(old)))
    matched: dict[int, int] = {}  # clip number → index in `old`

    # Same content at the same number first, then same content moved to another number.
    for n in notes:
        for i in sorted(unused):
            if old[i].fingerprint == fingerprints[n.number] and old[i].number == n.number:
                matched[n.number] = i
                unused.discard(i)
                break
    for n in notes:
        if n.number in matched:
            continue
        for i in sorted(unused, key=lambda i: old[i].number):
            if old[i].fingerprint == fingerprints[n.number]:
                matched[n.number] = i
                unused.discard(i)
                break

    replaced = {old[i].number for i in unused}  # previous clips whose content is gone
    actions: list[Action] = []
    for n in notes:
        i = matched.get(n.number)
        if i is None:
            kind = CHANGED if n.number in replaced else NEW
            actions.append(Action(n.number, kind))
            continue
        entry = old[i]
        if entry.number != n.number:
            sources = {
                k: out_dir / rel
                for k, rel in entry.files.items()
                if k in wanted and (out_dir / rel).is_file()
            }
            actions.append(Action(n.number, RENAMED, entry, sources))
        elif _has_files(entry, out_dir, wanted):
            actions.append(Action(n.number, UNCHANGED, entry))
        else:
            actions.append(Action(n.number, MISSING, entry))

    orphans = [
        out_dir / old[i].files[k]
        for i in sorted(unused, key=lambda i: old[i].number)
        for k in OUTPUT_KINDS
        if k in old[i].files and (out_dir / old[i].files[k]).is_file()
    ]
    return actions, orphans


# JSON (French keys, see the spec) ↔ dataclasses.


def _advice_to_json(a: ClaudeAdvice) -> dict[str, Any]:
    return {"type": a.kind, "reponse": a.answer, "raison": a.reason, "modele": a.model}


def _advice_from_json(d: dict[str, Any]) -> ClaudeAdvice:
    return ClaudeAdvice(d["type"], d["reponse"], d["raison"], d["modele"])


def _clip_to_json(c: ClipEntry) -> dict[str, Any]:
    return {
        "numero": c.number,
        "reference": c.reference,
        "fragments_trouves": c.found_fragments,
        "empreinte": c.fingerprint,
        "notes": {"debut": format_tc(c.noted_start), "fin": format_tc(c.noted_end)},
        "retenu": {
            "debut": format_tc(c.cut.start),
            "fin": format_tc(c.cut.end),
            "methode": c.cut.method,
            "score": c.cut.score,
            "doute": c.cut.doubt,
        },
        "avis_claude": _advice_to_json(c.claude_advice) if c.claude_advice else None,
        "duree_s": round(c.duration_s, 3),
        "fichiers": {k: v.replace("\\", "/") for k, v in c.files.items()},  # same on Windows
    }


def _clip_from_json(d: dict[str, Any]) -> ClipEntry:
    cut = d["retenu"]
    return ClipEntry(
        number=int(d["numero"]),
        reference=d["reference"],
        found_fragments=list(d["fragments_trouves"]),
        fingerprint=d["empreinte"],
        noted_start=parse_tc(d["notes"]["debut"]),
        noted_end=parse_tc(d["notes"]["fin"]),
        cut=Cut(
            parse_tc(cut["debut"]), parse_tc(cut["fin"]), cut["methode"], cut["score"], cut["doute"]
        ),
        claude_advice=_advice_from_json(d["avis_claude"]) if d["avis_claude"] else None,
        duration_s=float(d["duree_s"]),
        files=dict(d["fichiers"]),
    )


def _to_json(index: FilmIndex) -> dict[str, Any]:
    track = index.audio_track
    return {
        "version": INDEX_VERSION,
        "film": {
            "titre": index.title,
            "abreviation": index.abbreviation,
            "fichier": index.film_file,
            "piste_audio": (
                {
                    "index": track.index,
                    "langue": track.language,
                    "titre": track.title,
                    "canaux": track.channels,
                }
                if track
                else None
            ),
        },
        "avis_claude": [_advice_to_json(a) for a in index.claude_advice],
        "extraits": [_clip_to_json(c) for c in index.clips],
    }


def _from_json(data: dict[str, Any]) -> FilmIndex:
    film = data["film"]
    track = film["piste_audio"]
    return FilmIndex(
        title=film["titre"],
        abbreviation=film["abreviation"],
        film_file=film["fichier"],
        audio_track=(
            AudioTrack(int(track["index"]), track["langue"], track["titre"], int(track["canaux"]))
            if track
            else None
        ),
        claude_advice=[_advice_from_json(a) for a in data["avis_claude"]],
        clips=[_clip_from_json(c) for c in data["extraits"]],
    )


def load_index(path: Path) -> FilmIndex | None:
    """The index written by the previous run, or None on a first run."""
    path = Path(path)
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if data.get("version") != INDEX_VERSION:
            raise ValueError(f"unknown version {data.get('version')!r}")
        return _from_json(data)
    except (ValueError, KeyError, TypeError, AttributeError) as exc:
        raise ClipsError(
            f"Cannot read {path}: {exc}\n"
            f"Delete it to render every clip again (no clip file is lost)."
        ) from exc


def save_index(index: FilmIndex, path: Path) -> None:
    """Writes the index next to its target first, then renames it."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    part = path.with_name(f".{path.name}.part")
    try:
        part.write_text(
            json.dumps(_to_json(index), ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        os.replace(part, path)
    finally:
        part.unlink(missing_ok=True)
