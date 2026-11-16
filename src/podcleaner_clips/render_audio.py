"""Audio clip rendering: cut, fades, transition sound, loudness normalization (ffmpeg)."""

import functools
import json
import math
import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

from podcleaner_clips.adjust import Cut
from podcleaner_clips.config import Settings
from podcleaner_clips.errors import ClipsError
from podcleaner_clips.media import AudioTrack, require_ffmpeg

SAMPLE_RATE = 48000
_LRA = 11
_FORMAT = f"aresample={SAMPLE_RATE},aformat=sample_fmts=fltp:channel_layouts=stereo"
# Shortest fade-out, when the next line starts right after the last word.
_MIN_FADE_S = 0.05


@dataclass(frozen=True)
class ClipLayout:
    """Where the film sound and the transition sound sit in the clip (seconds)."""

    film_start: float
    film_end: float
    fade_s: float
    transition_s: float | None
    # Shorter fade-out when the next line comes soon after the last word (None: fade_s).
    fade_out_s: float | None = None
    # Earliest start of the closing transition, from the film start (None: with the fade-out).
    outro_after_s: float | None = None

    @classmethod
    def for_cut(
        cls, cut: Cut, fade_s: float, transition_s: float | None, pause_s: float
    ) -> "ClipLayout":
        """The layout of a cut: after its last word, a pause of `pause_s` before the closing
        transition. When the next line starts sooner, the film sound stops before it with a
        shorter fade-out that starts after the last word, and silence fills the rest of the
        pause.
        """
        if cut.speech_end is None or not cut.start <= cut.speech_end <= cut.end:
            return cls(cut.start, cut.end, fade_s, transition_s)
        tail = cut.end - cut.speech_end
        fade_out = fade_s if tail >= fade_s else max(tail, _MIN_FADE_S)
        return cls(
            cut.start,
            cut.end,
            fade_s,
            transition_s,
            fade_out_s=fade_out,
            outro_after_s=cut.speech_end - cut.start + pause_s,
        )

    @property
    def clip_s(self) -> float:
        return self.film_end - self.film_start

    @property
    def fade_out(self) -> float:
        return self.fade_s if self.fade_out_s is None else self.fade_out_s

    @property
    def film_offset(self) -> float:
        """When the film sound starts: the fade-in happens during the end of the transition."""
        if self.transition_s is None:
            return 0.0
        return max(0.0, self.transition_s - self.fade_s)

    @property
    def outro_offset(self) -> float:
        """When the closing transition starts: with the fade-out, or after the pause."""
        start = self.clip_s - min(self.fade_out, self.clip_s / 2)
        if self.outro_after_s is not None:
            start = max(start, self.outro_after_s)
        return self.film_offset + start

    @property
    def total_s(self) -> float:
        if self.transition_s is None:
            return self.clip_s
        return max(self.film_offset + self.clip_s, self.outro_offset + self.transition_s)


def _ms(seconds: float) -> int:
    return round(seconds * 1000)


def ffmpeg_seconds(seconds: float) -> str:
    return f"{seconds:.3f}".rstrip("0").rstrip(".")


def film_chain(layout: ClipLayout, track: int = 0) -> str:
    """The film sound of the clip (input 0, already cut): 48 kHz stereo, with its fades."""
    clip = layout.clip_s
    fade_in, fade_out = min(layout.fade_s, clip / 2), min(layout.fade_out, clip / 2)
    return (
        f"[0:a:{track}]asetpts=PTS-STARTPTS,{_FORMAT},"
        f"afade=t=in:d={ffmpeg_seconds(fade_in)},"
        f"afade=t=out:st={ffmpeg_seconds(clip - fade_out)}:d={ffmpeg_seconds(fade_out)}"
    )


def audio_filter(
    layout: ClipLayout,
    with_transition: bool,
    track: int = 0,
    film_norm: str | None = None,
    transition_gain_db: float = 0.0,
) -> str:
    """The -filter_complex graph: input 0 is the film (already cut), 1 the transition sound.

    `film_norm` brings the film sound to its loudness, `transition_gain_db` the transition
    sound to its own, before they are mixed. The result is labelled [mix].
    """
    film = film_chain(layout, track)
    if film_norm:
        film += f",{film_norm},{_FORMAT}"  # loudnorm works at 192 kHz: back to 48 kHz
    # adelay leaves its silence without timestamps (ffmpeg 7.1), which then cuts the mix
    # short: timestamps are rebuilt from the sample count after it.
    delay = "all=1,asetpts=N/SR/TB"
    total = ffmpeg_seconds(layout.total_s)
    end = f"apad=whole_dur={total},atrim=end={total}[mix]"
    if not with_transition:
        return f"{film},{end}"
    gain = f"volume={transition_gain_db:.2f}dB,"
    return ";".join(
        [
            f"{film},adelay=delays={_ms(layout.film_offset)}:{delay}[film]",
            f"[1:a]asetpts=PTS-STARTPTS,{_FORMAT},{gain}asplit=2[intro][outro_raw]",
            f"[outro_raw]adelay=delays={_ms(layout.outro_offset)}:{delay}[outro]",
            f"[film][intro][outro]amix=inputs=3:normalize=0:duration=longest,{end}",
        ]
    )


def peak_limiter(true_peak: float) -> str:
    """Keeps the mix under `true_peak` dBTP (4× oversampling to catch the peaks between samples)."""
    limit = min(1.0, max(0.0625, 10 ** (true_peak / 20)))
    return (
        f"aresample={4 * SAMPLE_RATE},"
        f"alimiter=limit={limit:.4f}:attack=1:release=50:level=0:latency=1,"
        f"aresample={SAMPLE_RATE}"
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


def _loudnorm_measure(args: list[str], chain: str, target: str) -> dict[str, float] | None:
    """loudnorm's first-pass measurement of `chain`; None for silence (nothing to measure)."""
    log = run_ffmpeg(
        [
            *args,
            "-filter_complex",
            f"{chain},loudnorm={target}:print_format=json[out]",
            "-map",
            "[out]",
            "-f",
            "null",
            "-",
        ]
    )
    m = _last_json(log)
    keys = ("input_i", "input_tp", "input_lra", "input_thresh", "target_offset")
    try:
        measured = {k: float(m[k]) for k in keys}
    except (KeyError, ValueError) as exc:
        raise ClipsError(f"Unexpected loudness measurement from ffmpeg: {m}") from exc
    return measured if all(math.isfinite(v) for v in measured.values()) else None


@functools.lru_cache(maxsize=8)
def _transition_gain(path: str, mtime_ns: int, size: int, target_lufs: float) -> float:
    del mtime_ns, size  # part of the cache key only: a changed file is measured again
    measured = _loudnorm_measure(["-i", path], "[0:a]anull", f"I={target_lufs:g}")
    return 0.0 if measured is None else target_lufs - measured["input_i"]


def transition_gain_db(transition: Path, target_lufs: float) -> float:
    """Gain (dB) that brings the transition sound to `target_lufs` (0 for a too-short sound)."""
    stat = Path(transition).stat()
    return _transition_gain(str(transition), stat.st_mtime_ns, stat.st_size, target_lufs)


def render_audio(
    film: Path,
    track: AudioTrack,
    layout: ClipLayout,
    transition: Path | None,
    out_wav: Path,
    s: Settings,
) -> None:
    """Writes the clip as a 48 kHz 24-bit stereo WAV.

    The film sound is brought to `s.lufs` and the transition sound to `s.transition_lufs`,
    each on its own, then the mix is kept under `s.true_peak`.
    """
    if not Path(film).is_file():
        raise ClipsError(f"Film not found: {film}")
    with_transition = transition is not None and layout.transition_s is not None
    inputs = _inputs(film, layout, transition if with_transition else None)
    target = f"I={s.lufs:g}:TP={s.true_peak:g}:LRA={_LRA}"

    # Pass 1: measure the film sound of the clip alone (with its fades).
    m = _loudnorm_measure(_inputs(film, layout, None), film_chain(layout, track.index), target)
    film_norm = None
    if m is not None:  # silence: nothing to normalize
        film_norm = (
            f"loudnorm={target}:measured_I={m['input_i']}:measured_TP={m['input_tp']}:"
            f"measured_LRA={m['input_lra']}:measured_thresh={m['input_thresh']}:"
            f"offset={m['target_offset']}:linear=true"
        )
    gain = transition_gain_db(transition, s.transition_lufs) if with_transition else 0.0
    graph = audio_filter(layout, with_transition, track.index, film_norm, gain)
    final = f"{graph};[mix]{peak_limiter(s.true_peak)}[out]"

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
