import json
import subprocess
from pathlib import Path

import numpy as np
import pytest
from make_test_film import make_test_film

from podcleaner_clips.config import Settings
from podcleaner_clips.errors import ClipsError
from podcleaner_clips.media import AudioTrack, VideoInfo, probe
from podcleaner_clips.render_audio import ClipLayout, render_audio
from podcleaner_clips.render_video import display_size, render_video

S = Settings(episodes_dir=Path("episodes"))
VFF = AudioTrack(0, "fre", "Français VFF", 2)
WITH_TRANSITION = ClipLayout(2.0, 8.0, 0.7, 1.5)  # film from 0.8 s to 6.8 s, total 7.6 s


def streams(path: Path) -> dict[str, dict]:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-print_format", "json", "-show_streams", path],
        check=True,
        capture_output=True,
    ).stdout
    return {s["codec_type"]: s for s in json.loads(out)["streams"]}


def luma(path: Path, t: float) -> float:
    """Mean luma (0-255) of the frame shown at `t` seconds."""
    out = subprocess.run(
        ["ffmpeg", "-v", "error", "-ss", str(t), "-i", path, "-frames:v", "1",
         "-f", "rawvideo", "-pix_fmt", "gray", "-"],
        check=True,
        capture_output=True,
    ).stdout  # fmt: skip
    assert out, f"no frame at {t} s"
    return float(np.frombuffer(out, dtype=np.uint8).mean())


def render(film: Path, layout: ClipLayout, transition: Path | None, tmp_path: Path) -> Path:
    wav, mp4 = tmp_path / "clip.wav", tmp_path / "clip.mp4"
    render_audio(film, VFF, layout, transition, wav, S)
    video = probe(film).video
    assert video is not None
    render_video(film, video, layout, wav, mp4)
    return mp4


def test_display_size_applies_the_pixel_aspect_ratio():
    assert display_size(VideoInfo(1920, 800, "24000/1001", "1:1")) == (1920, 800)
    assert display_size(VideoInfo(320, 240, "24", "4:3")) == (426, 240)
    assert display_size(VideoInfo(720, 576, "25", "64:45")) == (1024, 576)


def test_video_matches_audio_duration(test_film, transition_wav, tmp_path):
    mp4 = render(test_film, WITH_TRANSITION, transition_wav, tmp_path)

    info = streams(mp4)
    assert info["video"]["codec_name"] == "h264"
    assert info["video"]["pix_fmt"] == "yuv420p"
    assert info["audio"]["codec_name"] == "aac"
    assert float(info["video"]["duration"]) == pytest.approx(7.6, abs=0.1)
    assert float(info["audio"]["duration"]) == pytest.approx(7.6, abs=0.1)
    assert sorted(p.name for p in tmp_path.iterdir()) == ["clip.mp4", "clip.wav"]


def test_black_during_transitions(test_film, transition_wav, tmp_path):
    mp4 = render(test_film, WITH_TRANSITION, transition_wav, tmp_path)

    assert luma(mp4, 0.2) < 20  # opening transition
    assert luma(mp4, 0.8 + 1.0) > 20  # film picture
    assert luma(mp4, 7.3) < 20  # closing transition, after the film sound


def test_no_transition_has_no_black(test_film, tmp_path):
    mp4 = render(test_film, ClipLayout(2.0, 8.0, 0.7, None), None, tmp_path)

    assert luma(mp4, 0.0) > 20
    assert float(streams(mp4)["video"]["duration"]) == pytest.approx(6.0, abs=0.1)


def test_anamorphic_hevc_10bit_23976(tmp_path):
    film = make_test_film(tmp_path / "film hevc.mkv", duration=8.0, video="hevc10_anamorphic")
    out = tmp_path / "out"
    out.mkdir()
    mp4 = render(film, ClipLayout(1.0, 6.0, 0.7, None), None, out)

    video = streams(mp4)["video"]
    assert video["pix_fmt"] == "yuv420p"
    assert video["sample_aspect_ratio"] in ("1:1", "N/A")
    assert (video["width"], video["height"]) == (426, 240)
    assert video["r_frame_rate"] == "24000/1001"


def test_failed_render_leaves_no_file(test_film, tmp_path):
    out = tmp_path / "clip.mp4"
    video = probe(test_film).video
    assert video is not None
    with pytest.raises(ClipsError):
        render_video(test_film, video, WITH_TRANSITION, tmp_path / "missing.wav", out)
    assert list(tmp_path.iterdir()) == []
