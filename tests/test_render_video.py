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
from podcleaner_clips.render_video import display_size, render_video, video_filter

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
    assert luma(mp4, 0.8 + 1.0) > 20  # film picture, after its fade-in
    assert luma(mp4, 7.3) < 20  # closing transition, after the film sound


def lit(path: Path, t: float, full: float) -> float:
    """How lit the frame at `t` is, from 0 (black, luma 16) to 1 (as bright as `full`)."""
    return (luma(path, t) - 16) / (full - 16)


def test_film_picture_fades_from_and_to_black(test_film, transition_wav, tmp_path):
    mp4 = render(test_film, WITH_TRANSITION, transition_wav, tmp_path)
    start = WITH_TRANSITION.film_offset  # the film picture and sound start together
    end = start + WITH_TRANSITION.clip_s
    full = luma(mp4, start + 2.0)

    assert lit(mp4, start + 0.05, full) < 0.25  # beginning of the fade-in
    assert 0.25 < lit(mp4, start + 0.35, full) < 0.75  # halfway
    assert lit(mp4, start + 0.8, full) > 0.85  # after the 0.7 s fade
    assert lit(mp4, end - 0.8, full) > 0.85  # before the fade-out
    assert lit(mp4, end - 0.05, full) < 0.25  # end of the fade-out


def test_no_transition_fades_in_from_black(test_film, tmp_path):
    mp4 = render(test_film, ClipLayout(2.0, 8.0, 0.7, None), None, tmp_path)

    full = luma(mp4, 2.0)
    assert full > 20
    assert lit(mp4, 0.0, full) < 0.2
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


@pytest.mark.parametrize(
    "layout, fades",
    [
        (ClipLayout(10.0, 16.0, 0.7, 1.5), ["fade=t=in:st=0:d=0.7", "fade=t=out:st=5.3:d=0.7"]),
        (ClipLayout(10.0, 11.0, 0.7, None), ["fade=t=in:st=0:d=0.5", "fade=t=out:st=0.5:d=0.5"]),
        (ClipLayout(10.0, 16.0, 0.0, None), []),
    ],
)
def test_video_filter_fades(layout, fades):
    graph = video_filter(VideoInfo(1920, 800, "24", "1:1"), layout).removesuffix("[v]")
    steps = graph.split(",")
    assert [step for step in steps if step.startswith("fade=")] == fades
    if fades and layout.transition_s:  # on the film picture, before the black is added
        assert steps.index(fades[-1]) < next(i for i, x in enumerate(steps) if x.startswith("tpad"))


def colour(path: Path, t: float, x: int, y: int) -> tuple[int, int, int]:
    """RGB of the pixel (x, y) of the frame shown at `t` seconds."""
    out = subprocess.run(
        ["ffmpeg", "-v", "error", "-ss", str(t), "-i", path, "-frames:v", "1",
         "-vf", f"format=rgb24,crop=1:1:{x}:{y}", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
        check=True,
        capture_output=True,
    ).stdout  # fmt: skip
    return tuple(out[:3])


def test_transition_video_replaces_the_black(test_film, transition_mp4, tmp_path):
    layout = ClipLayout(2.0, 8.0, 0.7, 2.5)  # film picture from 1.8 s to 7.8 s, total 9.6 s
    wav, mp4 = tmp_path / "clip.wav", tmp_path / "clip.mp4"
    transition = tmp_path / "t.wav"
    subprocess.run(
        ["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "sine=frequency=330:duration=2.5",
         "-ac", "2", str(transition)],
        check=True,
    )  # fmt: skip
    render_audio(test_film, VFF, layout, transition, wav, S)
    video = probe(test_film).video
    assert video is not None
    render_video(test_film, video, layout, wav, mp4, transition_mp4)

    width, height = display_size(video)
    middle = (width // 2, height // 2)
    r, g, b = colour(mp4, 0.2, *middle)  # opening: the transition video, looped past 0.6 s
    assert r > 150 and g < 80 and b < 80
    assert colour(mp4, 1.0, *middle)[0] > 150  # still red after the first loop
    assert max(colour(mp4, 0.2, 2, height // 2)) < 40  # bars: the square is fitted, not stretched
    assert luma(mp4, 1.78) < 30  # faded to black just before the film
    assert luma(mp4, 3.5) > 40  # the film
    assert colour(mp4, 9.4, *middle)[0] > 150  # closing: the transition video again

    info = streams(mp4)
    assert float(info["video"]["duration"]) == pytest.approx(9.6, abs=0.1)
    assert float(info["audio"]["duration"]) == pytest.approx(9.6, abs=0.1)
    assert info["audio"]["codec_name"] == "aac"  # one sound only: the clip's


def test_picture_goes_on_until_the_transition_when_the_sound_stops_early(
    test_film, transition_wav, tmp_path
):
    """Next line 0.3 s after the last word: the sound stops, the picture fades out until the
    closing transition, and the MP4 lasts as long as the WAV."""
    from podcleaner_clips.adjust import Cut

    layout = ClipLayout.for_cut(Cut(2.0, 8.0, "claude", None, None, 7.7), 0.7, 1.5, 0.5)
    assert layout.picture_s == pytest.approx(6.2)
    graph = video_filter(VideoInfo(320, 240, "24", "1:1"), layout)
    assert "trim=duration=6.2" in graph and "fade=t=out:st=5.5:d=0.7" in graph

    S = Settings(episodes_dir=tmp_path)
    wav, mp4 = tmp_path / "clip.wav", tmp_path / "clip.mp4"
    render_audio(test_film, AudioTrack(0, "fre", "VFF", 2), layout, transition_wav, wav, S)
    render_video(test_film, probe(test_film).video, layout, wav, mp4)
    duration = float(
        json.loads(
            subprocess.run(
                ["ffprobe", "-v", "error", "-print_format", "json", "-show_format", mp4],
                check=True,
                capture_output=True,
            ).stdout
        )["format"]["duration"]
    )
    assert duration == pytest.approx(layout.total_s, abs=0.1)
