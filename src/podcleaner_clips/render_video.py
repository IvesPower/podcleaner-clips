"""Video clip rendering: black screen during the transition, film picture, clip sound (ffmpeg)."""

import os
from fractions import Fraction
from pathlib import Path

from podcleaner_clips.errors import ClipsError
from podcleaner_clips.media import VideoInfo
from podcleaner_clips.render_audio import ClipLayout, ffmpeg_seconds, run_ffmpeg

_FALLBACK_FPS = "24"


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


def video_filter(video: VideoInfo, layout: ClipLayout) -> str:
    """The -filter_complex graph: input 0 is the film (already cut). Labelled [v].

    The picture is black while the film sound has not started and after it stops, so it
    stays in sync with the clip sound (the transition plays over black).
    """
    width, height = display_size(video)
    fps = _ratio(video.fps, _FALLBACK_FPS)
    steps = [
        "[0:V:0]setpts=PTS-STARTPTS",  # V: skips cover art
        f"scale={width}:{height}",
        "setsar=1",
        f"fps={fps.numerator}/{fps.denominator}",
        "format=yuv420p",
        f"trim=duration={ffmpeg_seconds(layout.clip_s)}",
    ]
    before = layout.film_offset
    after = layout.total_s - layout.film_offset - layout.clip_s
    if before > 0 or after > 0:
        steps.append(
            f"tpad=start_mode=add:start_duration={ffmpeg_seconds(before)}"
            f":stop_mode=add:stop_duration={ffmpeg_seconds(max(after, 0.0))}:color=black"
        )
    return ",".join(steps) + "[v]"


def render_video(
    film: Path, video: VideoInfo, layout: ClipLayout, audio_wav: Path, out_mp4: Path
) -> None:
    """Writes the clip as an H.264 + AAC MP4 whose sound is the rendered WAV."""
    if not Path(film).is_file():
        raise ClipsError(f"Film not found: {film}")
    if not Path(audio_wav).is_file():
        raise ClipsError(f"Clip sound not found: {audio_wav}")

    out_mp4 = Path(out_mp4)
    part = out_mp4.with_name(f".{out_mp4.stem}.part.mp4")
    try:
        run_ffmpeg(
            [
                "-ss", ffmpeg_seconds(layout.film_start),
                "-t", ffmpeg_seconds(layout.clip_s),
                "-i", str(film),
                "-i", str(audio_wav),
                "-filter_complex", video_filter(video, layout),
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
