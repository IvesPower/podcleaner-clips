"""Film analysis with ffprobe/ffmpeg: tracks, dub choice, subtitles, audio windows.

All times are on the film clock as a player shows it: ffmpeg shifts the timeline so it
starts at 0 (e.g. the few ms of AAC priming), both when extracting subtitles and when
seeking with -ss, so subtitle times and decode_window offsets match.
"""

import json
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from podcleaner_clips.errors import ClipsError

FRENCH_LANGUAGES = {"fre", "fra", "fr", "fr-ca"}
TEXT_SUBTITLE_CODECS = {"subrip", "ass", "ssa", "mov_text", "webvtt"}
DECODE_RATE = 16000

_FRENCH_TITLE = re.compile(r"\bVF|fran[cç]ais|french", re.IGNORECASE)
_VFQ_TITLE = re.compile(r"\bVFQ\b|qu[ée]bec|canad", re.IGNORECASE)
_VFF_TITLE = re.compile(r"\bVFF\b|\bfrance\b|\bVF\b", re.IGNORECASE)
_FORCED_TITLE = re.compile(r"forc[eé]", re.IGNORECASE)
_FULL_TITLE = re.compile(r"complet|full|\bSDH\b", re.IGNORECASE)


@dataclass(frozen=True)
class AudioTrack:
    index: int  # rank among audio tracks, for -map 0:a:N
    language: str | None
    title: str | None
    channels: int


@dataclass(frozen=True)
class SubtitleTrack:
    index: int  # rank among subtitle tracks, for -map 0:s:N
    language: str | None
    title: str | None
    codec: str


@dataclass(frozen=True)
class VideoInfo:
    width: int
    height: int
    fps: str  # ffprobe fraction, e.g. 24000/1001
    sar: str


@dataclass(frozen=True)
class MediaInfo:
    duration: float
    audio: list[AudioTrack]
    subtitles: list[SubtitleTrack]
    video: VideoInfo | None  # first video stream that is not cover art


def require_ffmpeg() -> None:
    if shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None:
        raise ClipsError(
            "ffmpeg not found. Install it (macOS: brew install ffmpeg; "
            "Windows: winget install ffmpeg) and run again."
        )


def probe(path: Path) -> MediaInfo:
    path = Path(path)
    if not path.is_file():
        raise ClipsError(f"Film not found: {path}")
    out = _run(
        ["ffprobe", "-v", "error", "-print_format", "json", "-show_format", "-show_streams"],
        path,
    )
    data = json.loads(out)
    audio: list[AudioTrack] = []
    subtitles: list[SubtitleTrack] = []
    video: VideoInfo | None = None
    for stream in data.get("streams", []):
        kind = stream.get("codec_type")
        tags = {k.lower(): v for k, v in stream.get("tags", {}).items()}
        language, title = tags.get("language"), tags.get("title")
        if kind == "audio":
            audio.append(AudioTrack(len(audio), language, title, int(stream.get("channels", 0))))
        elif kind == "subtitle":
            codec = stream.get("codec_name", "")
            subtitles.append(SubtitleTrack(len(subtitles), language, title, codec))
        elif kind == "video" and video is None:
            if stream.get("disposition", {}).get("attached_pic"):
                continue
            sar = stream.get("sample_aspect_ratio", "1:1")
            video = VideoInfo(
                width=int(stream["width"]),
                height=int(stream["height"]),
                fps=stream.get("r_frame_rate", "0/0"),
                sar=sar if sar and sar != "0:1" else "1:1",
            )
    duration = float(data.get("format", {}).get("duration", 0.0))
    return MediaInfo(duration, audio, subtitles, video)


def _is_french(language: str | None, title: str | None) -> bool:
    if language and language.lower() in FRENCH_LANGUAGES:
        return True
    return bool(title and _FRENCH_TITLE.search(title))


def _dub(track: AudioTrack) -> str | None:
    title = track.title or ""
    if _VFQ_TITLE.search(title) or (track.language or "").lower() == "fr-ca":
        return "VFQ"
    if _VFF_TITLE.search(title):
        return "VFF"
    return None


def _describe_tracks(tracks: list[AudioTrack]) -> str:
    return ", ".join(
        f'{t.index} {t.language or "?"} "{t.title or ""}" {t.channels} channels' for t in tracks
    )


def choose_audio_track(
    tracks: list[AudioTrack], forced: int | None, preferred_dub: str = "VFF"
) -> tuple[AudioTrack, str | None]:
    """The track to use and an optional warning for the user."""
    if not tracks:
        raise ClipsError("The film has no audio track.")
    if forced is not None:
        if not 0 <= forced < len(tracks):
            raise ClipsError(
                f"Audio track {forced} does not exist. Tracks: {_describe_tracks(tracks)}."
            )
        return tracks[forced], None
    french = [t for t in tracks if _is_french(t.language, t.title)]
    if french:
        preferred = [t for t in french if _dub(t) == preferred_dub]
        return (preferred or french)[0], None
    return tracks[0], (
        f"No track marked French: using track 0. Tracks: {_describe_tracks(tracks)}. "
        "Choose one with --audio-track N."
    )


def choose_subtitle_track(tracks: list[SubtitleTrack]) -> SubtitleTrack | None:
    """Full French text subtitles, never forced ones; None when there are none."""
    usable = [
        t
        for t in tracks
        if t.codec in TEXT_SUBTITLE_CODECS
        and _is_french(t.language, t.title)
        and not _FORCED_TITLE.search(t.title or "")
    ]
    full = [t for t in usable if _FULL_TITLE.search(t.title or "")]
    return (full or usable or [None])[0]


def extract_subtitles(path: Path, track: SubtitleTrack) -> str:
    """The subtitle track as SRT text."""
    out = _run(
        ["ffmpeg", "-v", "error", "-i"], path, ["-map", f"0:s:{track.index}", "-f", "srt", "-"]
    )
    return out.decode("utf-8", errors="replace")


def decode_window(path: Path, track: int, start: float, duration: float) -> np.ndarray:
    """Mono 16 kHz float32 samples of an audio track, from `start` for `duration` seconds."""
    out = _run(
        ["ffmpeg", "-v", "error", "-ss", f"{start:.3f}", "-t", f"{duration:.3f}", "-i"],
        path,
        ["-map", f"0:a:{track}", "-ac", "1", "-ar", str(DECODE_RATE), "-f", "f32le", "-"],
    )
    return np.frombuffer(out, dtype=np.float32)


def _run(before: list[str], path: Path, after: list[str] | None = None) -> bytes:
    try:
        proc = subprocess.run([*before, str(path), *(after or [])], capture_output=True)
    except FileNotFoundError:
        require_ffmpeg()
        raise
    if proc.returncode != 0:
        detail = proc.stderr.decode("utf-8", errors="replace").strip()
        raise ClipsError(f"ffmpeg could not read {path}: {detail}")
    return proc.stdout
