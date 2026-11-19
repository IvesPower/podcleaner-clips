"""Video clip rendering: black screen during the transition, film picture faded in and out of
black, clip sound (ffmpeg)."""

import os
from fractions import Fraction
from pathlib import Path

from podcleaner_clips.errors import ClipsError
from podcleaner_clips.media import VideoInfo
from podcleaner_clips.render_audio import ClipLayout, ffmpeg_seconds, run_ffmpeg

_FALLBACK_FPS = "24"
# Bumped when the picture changes for the same cut: a rerun then redoes the videos only.
# 1: black screen and hard cuts. 2: fade from and to black. 3: the picture goes on until the
# closing transition when the film sound stops early.
VIDEO_RENDER_VERSION = 3


def _ratio(text: str, fallback: str) -> Fraction:
    """An ffprobe ratio ("4:3", "24000/1001"); `fallback` when it is missing or zero."""
    try:
        value = Fraction(text.replace(":", "/"))
    except (ValueError, ZeroDivisionError):
        value = Fraction(0)
    return value if value > 0 else Fraction(fallback)


def _even(value: float) -> int:
    return max(2, 2 * round(value / 2))


def display_size(video: VideoInfo) -> tuple[int, int]:
    """Width and height as shown on screen (pixel aspect ratio applied), even for H.264."""
    sar = _ratio(video.sar, "1")
    return _even(video.width * sar), _even(video.height)


def _fades(duration: float, fade_s: float, *, fade_in: bool, fade_out: bool) -> list[str]:
    fade = min(fade_s, duration / 2)
    if fade <= 0:
        return []
    d = ffmpeg_seconds(fade)
    steps = [f"fade=t=in:st=0:d={d}"] if fade_in else []
    if fade_out:
        steps.append(f"fade=t=out:st={ffmpeg_seconds(duration - fade)}:d={d}")
    return steps


def video_filter(video: VideoInfo, layout: ClipLayout, transition_video: bool = False) -> str:
    """The -filter_complex graph: input 0 is the film (already cut), input 2 the transition
    video if any (looped). Labelled [v].

    While the film sound has not started and after it stops (the transition sound plays),
    the picture is black, or the transition video. The film picture fades in from black and
    out to black like the sound, over `layout.fade_s`; the transition video fades out to black
    before the film and in from black after it.
    """
    width, height = display_size(video)
    fps = _ratio(video.fps, _FALLBACK_FPS)
    common = [
        "setsar=1",
        f"fps={fps.numerator}/{fps.denominator}",
        "format=yuv420p",
    ]
    film = [
        "[0:V:0]setpts=PTS-STARTPTS",  # V: skips cover art
        f"scale={width}:{height}",
        *common,
        f"trim=duration={ffmpeg_seconds(layout.picture_s)}",
        *_fades(layout.picture_s, layout.fade_s, fade_in=True, fade_out=True),
    ]
    before = layout.film_offset
    after = max(layout.total_s - layout.film_offset - layout.picture_s, 0.0)
    if not transition_video or (before <= 0 and after <= 0):
        if before > 0 or after > 0:
            film.append(
                f"tpad=start_mode=add:start_duration={ffmpeg_seconds(before)}"
                f":stop_mode=add:stop_duration={ffmpeg_seconds(after)}:color=black"
            )
        return ",".join(film) + "[v]"

    # The transition video, fitted inside the film's frame (black bars), then one copy for
    # the opening and one for the closing, each from its first frame.
    parts = [",".join(film) + "[film]"]
    fitted = ",".join(
        [
            "[2:V:0]setpts=PTS-STARTPTS",
            f"scale={width}:{height}:force_original_aspect_ratio=decrease",
            f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:color=black",
            *common,
        ]
    )
    pieces = [(name, d) for name, d in (("intro", before), ("outro", after)) if d > 0]
    if len(pieces) == 2:
        parts.append(f"{fitted},split=2[introsrc][outrosrc]")
    else:
        parts.append(f"{fitted}[{pieces[0][0]}src]")
    for name, duration in pieces:
        steps = [
            f"[{name}src]trim=duration={ffmpeg_seconds(duration)}",
            "setpts=PTS-STARTPTS",
            *_fades(duration, layout.fade_s, fade_in=name == "outro", fade_out=name == "intro"),
        ]
        parts.append(",".join(steps) + f"[{name}]")
    used = {name for name, _ in pieces} | {"film"}
    order = [name for name in ("intro", "film", "outro") if name in used]
    parts.append("".join(f"[{name}]" for name in order) + f"concat=n={len(order)}:v=1:a=0[v]")
    return ";".join(parts)


def render_video(
    film: Path,
    video: VideoInfo,
    layout: ClipLayout,
    audio_wav: Path,
    out_mp4: Path,
    transition_video: Path | None = None,
) -> None:
    """Writes the clip as an H.264 + AAC MP4 whose sound is the rendered WAV.

    `transition_video` replaces the black screen during the transition sound (its own sound
    is not used).
    """
    if not Path(film).is_file():
        raise ClipsError(f"Film not found: {film}")
    if not Path(audio_wav).is_file():
        raise ClipsError(f"Clip sound not found: {audio_wav}")
    looped = (
        ["-stream_loop", "-1", "-i", str(transition_video)] if transition_video is not None else []
    )

    out_mp4 = Path(out_mp4)
    part = out_mp4.with_name(f".{out_mp4.stem}.part.mp4")
    try:
        run_ffmpeg(
            [
                "-ss", ffmpeg_seconds(layout.film_start),
                "-t", ffmpeg_seconds(layout.picture_s),
                "-i", str(film),
                "-i", str(audio_wav),
                *looped,
                "-filter_complex", video_filter(video, layout, transition_video is not None),
                "-map", "[v]",
                "-map", "1:a:0",
                "-map_chapters", "-1",  # film chapters would become an extra stream
                "-map_metadata", "-1",
                "-c:v", "libx264", "-crf", "18", "-preset", "medium",
                "-c:a", "aac", "-b:a", "192k",
                "-t", ffmpeg_seconds(layout.total_s),
                "-movflags", "+faststart",
                "-f", "mp4",
                str(part),
            ]
        )  # fmt: skip
        os.replace(part, out_mp4)
    finally:
        part.unlink(missing_ok=True)
