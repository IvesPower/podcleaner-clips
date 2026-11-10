"""Generate a small test film shaped like a real one: VFF, VO and VFQ tracks, cover art.

Usage: python scripts/make_test_film.py out.mkv
"""

import subprocess
import sys
import tempfile
from pathlib import Path

# (sine frequency, language, title) for audio tracks 0, 1 and 2.
AUDIO_TRACKS = [
    (660, "fre", "Français VFF"),
    (440, "eng", "English"),
    (880, "fre", "Français VFQ"),
]
# Video kinds: "h264" (320x240, 24 fps, square pixels) or "hevc10_anamorphic"
# (320x240 stored, 4:3 pixels, 23.976 fps, 10-bit HEVC), like many Blu-ray rips.
VIDEO_KINDS = {
    "h264": ("24", ["-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p"]),
    "hevc10_anamorphic": (
        "24000/1001",
        [
            "-vf", "setsar=4/3",
            "-c:v", "libx265", "-preset", "ultrafast", "-pix_fmt", "yuv420p10le",
            "-x265-params", "log-level=error",
        ],
    ),
}  # fmt: skip


def make_test_film(
    out: Path,
    duration: float = 12.0,
    *,
    vf_channels: int = 2,
    video: str = "h264",
    subtitles: str | None = None,
) -> Path:
    """Write a .mkv test film to `out` and return its path.

    `subtitles` is SRT content added as a French "Complets" text subtitle track.
    """
    if video not in VIDEO_KINDS:
        raise ValueError(f"Unknown video kind: {video!r}")
    rate, video_args = VIDEO_KINDS[video]
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        cover = Path(tmp) / "cover.jpg"
        _run(
            ["-f", "lavfi", "-i", "color=c=red:s=64x64", "-frames:v", "1", str(cover)],
        )
        args = ["-f", "lavfi", "-i", f"testsrc=size=320x240:rate={rate}:duration={duration}"]
        for freq, _, _ in AUDIO_TRACKS:
            args += ["-f", "lavfi", "-i", f"sine=frequency={freq}:duration={duration}"]
        if subtitles is not None:
            srt = Path(tmp) / "subs.srt"
            srt.write_text(subtitles, encoding="utf-8")
            args += ["-i", str(srt)]
        args += ["-map", "0:v"]
        for i in range(len(AUDIO_TRACKS)):
            args += ["-map", f"{i + 1}:a"]
        if subtitles is not None:
            args += ["-map", f"{len(AUDIO_TRACKS) + 1}:s"]
        args += video_args
        args += ["-c:a", "aac", "-ac", "2", "-ac:a:0", str(vf_channels)]
        for i, (_, lang, title) in enumerate(AUDIO_TRACKS):
            args += [
                f"-metadata:s:a:{i}",
                f"language={lang}",
                f"-metadata:s:a:{i}",
                f"title={title}",
            ]
        if subtitles is not None:
            args += ["-c:s", "srt", "-metadata:s:s:0", "language=fre"]
            args += ["-metadata:s:s:0", "title=Complets"]
        args += ["-attach", str(cover), "-metadata:s:t:0", "mimetype=image/jpeg"]
        args += ["-metadata:s:t:0", "filename=cover.jpg", str(out)]
        _run(args)
    return out


def _run(args: list[str]) -> None:
    subprocess.run(
        ["ffmpeg", "-v", "error", "-y", *args], check=True, capture_output=True, text=True
    )


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("Usage: python scripts/make_test_film.py out.mkv")
    print(make_test_film(Path(sys.argv[1])))
