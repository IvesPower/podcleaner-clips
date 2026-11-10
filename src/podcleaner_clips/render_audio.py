"""Audio clip rendering: cut, fades, transition sound, loudness normalization (ffmpeg)."""

import json
import math
import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

from podcleaner_clips.config import Settings
from podcleaner_clips.errors import ClipsError
from podcleaner_clips.media import AudioTrack, require_ffmpeg

SAMPLE_RATE = 48000
_LRA = 11
_FORMAT = f"aresample={SAMPLE_RATE},aformat=sample_fmts=fltp:channel_layouts=stereo"


@dataclass(frozen=True)
class ClipLayout:
    """Where the film sound and the transition sound sit in the clip (seconds)."""

    film_start: float
    film_end: float
    fade_s: float
    transition_s: float | None

    @property
    def clip_s(self) -> float:
        return self.film_end - self.film_start

    @property
    def film_offset(self) -> float:
        """When the film sound starts: the fade-in happens during the end of the transition."""
        if self.transition_s is None:
            return 0.0
        return max(0.0, self.transition_s - self.fade_s)

    @property
    def outro_offset(self) -> float:
        """When the closing transition starts: with the fade-out."""
        return self.film_offset + self.clip_s - self.fade_s

    @property
    def total_s(self) -> float:
        if self.transition_s is None:
            return self.clip_s
        return max(self.film_offset + self.clip_s, self.outro_offset + self.transition_s)


def _ms(seconds: float) -> int:
    return round(seconds * 1000)


def ffmpeg_seconds(seconds: float) -> str:
    return f"{seconds:.3f}".rstrip("0").rstrip(".")


def audio_filter(layout: ClipLayout, with_transition: bool, track: int = 0) -> str:
    """The -filter_complex graph: input 0 is the film (already cut), 1 the transition sound.

    The result is labelled [mix].
    """
    clip = layout.clip_s
    fade = min(layout.fade_s, clip / 2)
    d, out_at = ffmpeg_seconds(fade), ffmpeg_seconds(clip - fade)
    film = (
        f"[0:a:{track}]asetpts=PTS-STARTPTS,{_FORMAT},"
        f"afade=t=in:d={d},afade=t=out:st={out_at}:d={d}"
    )
    # adelay leaves its silence without timestamps (ffmpeg 7.1), which then cuts the mix
    # short: timestamps are rebuilt from the sample count after it.
    delay = "all=1,asetpts=N/SR/TB"
    total = ffmpeg_seconds(layout.total_s)
    end = f"apad=whole_dur={total},atrim=end={total}[mix]"
    if not with_transition:
        return f"{film},{end}"
    return ";".join(
        [
            f"{film},adelay=delays={_ms(layout.film_offset)}:{delay}[film]",
            f"[1:a]asetpts=PTS-STARTPTS,{_FORMAT},asplit=2[intro][outro_raw]",
            f"[outro_raw]adelay=delays={_ms(layout.outro_offset)}:{delay}[outro]",
            f"[film][intro][outro]amix=inputs=3:normalize=0:duration=longest,{end}",
        ]
    )


def run_ffmpeg(args: list[str]) -> str:
    """Runs ffmpeg and returns its log (stderr)."""
    try:
        proc = subprocess.run(
            ["ffmpeg", "-hide_banner", "-nostats", "-y", *args], capture_output=True
        )
    except FileNotFoundError:
        require_ffmpeg()
        raise
    log = proc.stderr.decode("utf-8", errors="replace")
    if proc.returncode != 0:
        tail = "\n".join(log.strip().splitlines()[-5:])
        raise ClipsError(f"ffmpeg failed: {tail}")
    return log


def _inputs(film: Path, layout: ClipLayout, transition: Path | None) -> list[str]:
    args = [
        "-ss",
        ffmpeg_seconds(layout.film_start),
        "-t",
        ffmpeg_seconds(layout.clip_s),
        "-i",
        str(film),
    ]
    if transition is not None:
        args += ["-i", str(transition)]
    return args


def _last_json(log: str) -> dict:
    start = log.rfind("{")
    end = log.rfind("}")
    if start < 0 or end < start:
        raise ClipsError("ffmpeg did not report the loudness measurement.")
    return json.loads(log[start : end + 1])


def render_audio(
    film: Path,
    track: AudioTrack,
    layout: ClipLayout,
    transition: Path | None,
    out_wav: Path,
    s: Settings,
) -> None:
    """Writes the clip as a 48 kHz 24-bit stereo WAV at the target loudness."""
    if not Path(film).is_file():
        raise ClipsError(f"Film not found: {film}")
    with_transition = transition is not None and layout.transition_s is not None
    graph = audio_filter(layout, with_transition, track.index)
    inputs = _inputs(film, layout, transition if with_transition else None)
    target = f"I={s.lufs:g}:TP={s.true_peak:g}:LRA={_LRA}"

    # Pass 1: measure the mixed clip.
    log = run_ffmpeg(
        [
            *inputs,
            "-filter_complex",
            f"{graph};[mix]loudnorm={target}:print_format=json[out]",
            "-map",
            "[out]",
            "-f",
            "null",
            "-",
        ]
    )
    m = _last_json(log)
    try:
        measured = {k: float(m[k]) for k in ("input_i", "input_tp", "input_lra", "input_thresh")}
        offset = float(m["target_offset"])
    except (KeyError, ValueError) as exc:
        raise ClipsError(f"Unexpected loudness measurement from ffmpeg: {m}") from exc

    if all(math.isfinite(v) for v in measured.values()):
        norm = (
            f"loudnorm={target}:measured_I={measured['input_i']}:"
            f"measured_TP={measured['input_tp']}:measured_LRA={measured['input_lra']}:"
            f"measured_thresh={measured['input_thresh']}:offset={offset}:linear=true"
        )
        # loudnorm works at 192 kHz: come back to 48 kHz.
        final = f"{graph};[mix]{norm},aresample={SAMPLE_RATE}[out]"
    else:  # silence: nothing to normalize
        final = f"{graph};[mix]anull[out]"

    # Pass 2: write next to the target, then rename, so no half-written WAV is left.
    out_wav = Path(out_wav)
    part = out_wav.with_name(f".{out_wav.stem}.part.wav")
    try:
        run_ffmpeg(
            [
                *inputs,
                "-filter_complex",
                final,
                "-map",
                "[out]",
                "-ar",
                str(SAMPLE_RATE),
                "-c:a",
                "pcm_s24le",
                "-f",
                "wav",
                str(part),
            ]
        )
        os.replace(part, out_wav)
    finally:
        part.unlink(missing_ok=True)


_INTEGRATED = re.compile(r"^\s*I:\s+(-?[\d.]+|-inf) LUFS", re.MULTILINE)
_PEAK = re.compile(r"^\s*Peak:\s+(-?[\d.]+|-inf) dBFS", re.MULTILINE)


def measure_loudness(path: Path) -> tuple[float, float]:
    """(integrated loudness in LUFS, true peak in dBTP) of an audio file."""
    log = run_ffmpeg(["-i", str(path), "-filter_complex", "ebur128=peak=true", "-f", "null", "-"])
    integrated, peak = _INTEGRATED.findall(log), _PEAK.findall(log)
    if not integrated or not peak:
        raise ClipsError(f"ffmpeg did not report the loudness of {path}.")
    return float(integrated[-1]), float(peak[-1])
