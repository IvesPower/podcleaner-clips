"""End-to-end run: notes → film → cuts → audio and video clips → index and summary."""

import glob
import os
import tempfile
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

import typer

from podcleaner_clips.adjust import Cut, adjust_cut
from podcleaner_clips.claude import ClaudeAdvice, ClaudeClient
from podcleaner_clips.config import Settings, load_settings
from podcleaner_clips.errors import ClipsError
from podcleaner_clips.index import (
    CHANGED,
    INDEX_NAME,
    MISSING,
    NEW,
    OUTPUT_KINDS,
    RENAMED,
    UNCHANGED,
    Action,
    ClipEntry,
    FilmIndex,
    file_sha256,
    fingerprint,
    load_index,
    plan_actions,
    save_index,
)
from podcleaner_clips.media import (
    AudioTrack,
    MediaInfo,
    choose_audio_track,
    choose_subtitle_track,
    decode_window,
    extract_subtitles,
    probe,
    require_ffmpeg,
)
from podcleaner_clips.naming import clip_basename, film_folder_name, format_tc, title_from_film
from podcleaner_clips.notes import ClipNote, Notes, read_notes, write_abbreviation
from podcleaner_clips.render_audio import ClipLayout, render_audio
from podcleaner_clips.render_video import render_video
from podcleaner_clips.subtitles import Cue, find_anchors, parse_srt
from podcleaner_clips.transcribe import Transcriber, make_transcriber

_LABELS = {
    NEW: "new",
    CHANGED: "changed",
    UNCHANGED: "unchanged",
    RENAMED: "renamed",
    MISSING: "missing file redone",
}
_EXTENSIONS = {"audio": "wav", "video": "mp4"}
# A clip may end this much after the film's reported duration (rounding of the container).
_END_SLACK_S = 0.05


@dataclass(frozen=True)
class RunOptions:
    notes: Path
    film: Path | None = None
    transition: bool = True
    audio: bool = True
    video: bool = True
    adjust: bool = True
    dry_run: bool = False
    audio_track: int | None = None
    config: Path | None = None


@dataclass
class RunReport:
    index: FilmIndex | None  # None for a dry run
    failures: int
    out_dir: Path


@dataclass
class _Job:
    note: ClipNote
    action: Action
    name: str
    cut: Cut | None = None
    found: list[str] = field(default_factory=list)
    advice: ClaudeAdvice | None = None
    render: set[str] = field(default_factory=set)  # kinds to render
    keep: set[str] = field(default_factory=set)  # kinds whose existing file is kept
    renames: dict[str, Path] = field(default_factory=dict)  # kind → file to move
    error: str | None = None


def _rel(kind: str, name: str) -> str:
    return f"{kind}/{name}.{_EXTENSIONS[kind]}"


def _resolve_film(opts: RunOptions, notes: Notes, s: Settings) -> Path:
    if opts.film is not None:
        film = Path(opts.film).expanduser()
        if not film.is_file():
            raise ClipsError(f"Film not found: {film}")
        return film
    if not notes.film_file:
        raise ClipsError(
            f"No film for {opts.notes}: add a line `fichier: <path of the film>` at the top "
            "of the notes, or use --film."
        )
    given = Path(notes.film_file).expanduser()
    places = [given] if given.is_absolute() else [Path(opts.notes).parent / given]
    if s.films_dir is not None:
        if not given.is_absolute():
            places.append(s.films_dir / given)
        places.append(s.films_dir / given.name)
        places += sorted(s.films_dir.glob(f"*/{glob.escape(given.name)}"))
    for place in places:
        if place.is_file():
            return place
    searched = "\n".join(f"  {p}" for p in dict.fromkeys(places))
    if s.films_dir is not None:
        searched += f"\n  {s.films_dir / '*' / given.name}"
    raise ClipsError(f"Film not found. Searched:\n{searched}\nFix `fichier:` or use --film.")


def _transition(opts: RunOptions, s: Settings) -> tuple[Path | None, float | None, str | None]:
    if not opts.transition:
        return None, None, None
    path = s.transition_sound
    if path is None:
        raise ClipsError(
            "No transition sound: set son_transition in the configuration file, "
            "or use --no-transition."
        )
    if not path.is_file():
        raise ClipsError(f"Transition sound not found: {path} (son_transition).")
    duration = probe(path).duration
    if duration <= 0:
        raise ClipsError(f"The transition sound is empty: {path} (son_transition).")
    return path, duration, file_sha256(path)


def _render_settings(s: Settings, film: Path) -> dict:
    """Settings that change the clips' files (part of each clip's fingerprint)."""
    return {
        "film": film.name,
        "fade_s": s.fade_s,
        "lufs": s.lufs,
        "true_peak": s.true_peak,
        "tolerance_s": s.tolerance_s,
        "use_subtitles": s.use_subtitles,
        "score_found": s.score_found,
        "score_sure": s.score_sure,
        "sentence_gap_s": s.sentence_gap_s,
        "pad_before_s": s.pad_before_s,
        "pad_after_s": s.pad_after_s,
        "whisper_model": s.whisper_model,
    }


def _describe_track(t: AudioTrack) -> str:
    return f'{t.index} ({t.language or "?"}, "{t.title or ""}", {t.channels} channels)'


class _Subtitles:
    """The film's French subtitles, extracted once and only when a clip needs them."""

    def __init__(self, film: Path, info: MediaInfo, enabled: bool) -> None:
        self._film, self._info, self._enabled = film, info, enabled
        self._cues: list[Cue] | None = None

    def cues(self) -> list[Cue]:
        if self._cues is None:
            track = choose_subtitle_track(self._info.subtitles) if self._enabled else None
            self._cues = parse_srt(extract_subtitles(self._film, track)) if track else []
        return self._cues


def _choose_cut(
    note: ClipNote,
    film: Path,
    track: AudioTrack,
    duration: float,
    subtitles: _Subtitles,
    transcriber: Transcriber,
    claude: ClaudeClient,
    s: Settings,
) -> tuple[Cut, list[str], ClaudeAdvice | None]:
    lo = max(0.0, note.start - s.tolerance_s)
    hi = min(duration, note.end + s.tolerance_s)
    words = transcriber.words(decode_window(film, track.index, lo, hi - lo), offset=lo)
    cues = subtitles.cues()
    anchors = find_anchors(cues, note.fragments, note.start, note.end, s) if cues else []
    decision = adjust_cut(words, note.fragments, anchors, note.start, note.end, s)
    cut, advice = claude.choose_bounds(words, note.reference, decision, note.start, note.end, s)
    found = [m.fragment for m in decision.matches if m is not None]
    return cut, found, advice


def _apply_renames(jobs: list[_Job], out_dir: Path) -> None:
    """Moves files to their new names in two steps, so 01→02 and 02→03 never collide."""
    moving: list[tuple[Path, Path]] = []
    for job in jobs:
        for kind, source in job.renames.items():
            parked = source.with_name(f".{source.name}.moving")
            os.replace(source, parked)
            moving.append((parked, out_dir / _rel(kind, job.name)))
    for parked, target in moving:
        target.parent.mkdir(parents=True, exist_ok=True)
        os.replace(parked, target)


def _render(
    job: _Job,
    film: Path,
    info: MediaInfo,
    track: AudioTrack,
    layout: ClipLayout,
    transition: Path | None,
    out_dir: Path,
    s: Settings,
) -> None:
    audio_path = out_dir / _rel("audio", job.name)
    if "audio" in job.render:
        audio_path.parent.mkdir(parents=True, exist_ok=True)
        render_audio(film, track, layout, transition, audio_path, s)
    if "video" not in job.render:
        return
    assert info.video is not None  # checked before any render
    video_path = out_dir / _rel("video", job.name)
    video_path.parent.mkdir(parents=True, exist_ok=True)
    if "audio" in job.render or "audio" in job.keep:
        render_video(film, info.video, layout, audio_path, video_path)
        return
    with tempfile.TemporaryDirectory() as tmp:  # --video-only: the sound is not kept
        wav = Path(tmp) / "clip.wav"
        render_audio(film, track, layout, transition, wav, s)
        render_video(film, info.video, layout, wav, video_path)


def run(
    opts: RunOptions,
    *,
    transcriber: Transcriber | None = None,
    claude: ClaudeClient | None = None,
    echo: Callable[[str], None] = typer.echo,
) -> RunReport:
    """Cuts every clip of the notes file; only what changed since the last run is redone."""
    if not opts.audio and not opts.video:
        raise ClipsError("--audio-only and --video-only cannot be used together.")
    require_ffmpeg()
    s = load_settings(opts.config)
    notes_path = Path(opts.notes)
    notes = read_notes(notes_path)
    if not notes.clips and not notes.errors:
        raise ClipsError(
            f"No clip line in {notes_path} (expected, for example: 27:15 the line 27:37)."
        )
    film = _resolve_film(opts, notes, s)
    title = notes.title or title_from_film(film.name)
    info = probe(film)
    if opts.video and info.video is None:
        raise ClipsError(f"{film.name} has no picture: use --audio-only.")
    track, track_warning = choose_audio_track(info.audio, opts.audio_track, s.preferred_dub)
    transition, transition_s, transition_sha = _transition(opts, s)
    claude = claude if claude is not None else ClaudeClient(s)

    echo(f"Film: {film}")
    echo(f"Audio track: {_describe_track(track)}")

    abbr_advice = None
    if notes.abbreviation:
        abbr = notes.abbreviation
    else:
        abbr, abbr_advice = claude.propose_abbreviation(title, film.name)
        if not opts.dry_run:
            write_abbreviation(notes_path, abbr)
        echo(f"Abbreviation: {abbr}" + ("" if opts.dry_run else f" (written to {notes_path.name})"))

    out_dir = s.episodes_dir / film_folder_name(title)
    previous = load_index(out_dir / INDEX_NAME)
    wanted = {k for k, on in (("audio", opts.audio), ("video", opts.video)) if on}
    render_cfg = _render_settings(s, film)
    fingerprints = {
        n.number: fingerprint(
            n,
            adjust=opts.adjust,
            transition=transition is not None,
            track=track.index,
            transition_sha=transition_sha,
            render=render_cfg,
        )
        for n in notes.clips
    }
    actions, orphans = plan_actions(notes.clips, fingerprints, previous, out_dir, wanted)

    subtitles = _Subtitles(film, info, opts.adjust and s.use_subtitles)
    if opts.adjust and any(a.reuse is None for a in actions) and transcriber is None:
        transcriber = make_transcriber(s.whisper_model)
    jobs: list[_Job] = []
    for position, (note, action) in enumerate(zip(notes.clips, actions, strict=True), 1):
        job = _Job(note, action, clip_basename(abbr, note.number, note.reference))
        jobs.append(job)
        if note.end > info.duration + _END_SLACK_S:
            job.error = f"ends after the end of the film ({format_tc(info.duration)})"
            if action.reuse is not None:
                orphans += [out_dir / rel for rel in action.reuse.files.values()]
            continue
        if action.reuse is None:
            job.render = set(wanted)
            if not opts.adjust:
                job.cut = Cut(note.start, note.end, "notes", None, None)
                continue
            echo(f"[{position}/{len(notes.clips)}] {job.name}: finding the cut")
            try:
                assert transcriber is not None
                job.cut, job.found, job.advice = _choose_cut(
                    note, film, track, info.duration, subtitles, transcriber, claude, s
                )
            except ClipsError as exc:
                job.error = str(exc)
            continue
        entry = action.reuse
        job.cut, job.found, job.advice = entry.cut, entry.found_fragments, entry.claude_advice
        for kind in OUTPUT_KINDS:
            target = out_dir / _rel(kind, job.name)
            source = out_dir / entry.files[kind] if kind in entry.files else None
            if source is not None and source.is_file():
                job.keep.add(kind)
                if source != target:
                    job.renames[kind] = source
            elif kind in wanted:
                job.render.add(kind)

    layouts = {
        job.note.number: ClipLayout(job.cut.start, job.cut.end, s.fade_s, transition_s)
        for job in jobs
        if job.cut is not None and job.error is None
    }

    index = None
    if not opts.dry_run:
        _apply_renames([j for j in jobs if j.error is None], out_dir)
        to_render = [j for j in jobs if j.error is None and j.render]
        for position, job in enumerate(to_render, 1):
            echo(f"[{position}/{len(to_render)}] {job.name}: rendering")
            try:
                _render(job, film, info, track, layouts[job.note.number], transition, out_dir, s)
            except ClipsError as exc:
                job.error = str(exc)
        if abbr_advice is not None:
            advice = [abbr_advice]
        elif previous is not None and previous.abbreviation == abbr:
            advice = previous.claude_advice
        else:
            advice = []
        index = FilmIndex(
            title=title,
            abbreviation=abbr,
            film_file=str(film),
            audio_track=track,
            claude_advice=advice,
            clips=[
                ClipEntry(
                    number=j.note.number,
                    reference=j.note.reference,
                    found_fragments=j.found,
                    fingerprint=fingerprints[j.note.number],
                    noted_start=j.note.start,
                    noted_end=j.note.end,
                    cut=j.cut,
                    claude_advice=j.advice,
                    duration_s=layouts[j.note.number].total_s,
                    files={k: _rel(k, j.name) for k in sorted(j.render | j.keep)},
                )
                for j in jobs
                if j.error is None and j.cut is not None
            ],
        )
        save_index(index, out_dir / INDEX_NAME)

    written = {out_dir / _rel(k, j.name) for j in jobs for k in j.render | j.keep}
    orphans = [p for p in dict.fromkeys(orphans) if p not in written and p.is_file()]
    failures = _summary(jobs, layouts, notes, orphans, track_warning, claude, out_dir, opts, echo)
    return RunReport(index, failures, out_dir)


def _summary(
    jobs: list[_Job],
    layouts: dict[int, ClipLayout],
    notes: Notes,
    orphans: list[Path],
    track_warning: str | None,
    claude: ClaudeClient,
    out_dir: Path,
    opts: RunOptions,
    echo: Callable[[str], None],
) -> int:
    echo("")
    for job in jobs:
        n = job.note
        head = f"{n.number:02d}  {job.name}"
        if job.error is not None or job.cut is None:
            echo(f"{head}  error: {job.error}")
            continue
        kind = job.action.kind
        if kind == UNCHANGED and job.renames:
            kind = RENAMED
        echo(
            f"{head}  {format_tc(n.start)} > {format_tc(n.end)}  →  "
            f"{format_tc(job.cut.start)} > {format_tc(job.cut.end)}  "
            f"{layouts[n.number].total_s:.1f} s  {_LABELS[kind]}"
        )
        if job.cut.doubt:
            echo(f"    ⚠ {job.cut.doubt}")
    warnings = [*notes.errors]
    if track_warning:
        warnings.append(track_warning)
    warnings += claude.warnings
    if orphans:
        warnings.append("Files of clips no longer in the notes (kept):")
        warnings += [f"  {p}" for p in orphans]
    if warnings:
        echo("")
        for warning in warnings:
            echo(f"⚠ {warning}" if not warning.startswith("  ") else warning)
    echo("")
    echo("Dry run: nothing was written." if opts.dry_run else f"Clips: {out_dir}")
    return len(notes.errors) + sum(1 for j in jobs if j.error is not None)
