import json
import subprocess
from pathlib import Path

import numpy as np
import pytest
from make_test_film import make_test_film

from podcleaner_clips.config import Settings
from podcleaner_clips.errors import ClipsError
from podcleaner_clips.media import AudioTrack, probe
from podcleaner_clips.render_audio import ClipLayout, audio_filter, measure_loudness, render_audio

S = Settings(episodes_dir=Path("episodes"))
VFF = AudioTrack(0, "fre", "Français VFF", 2)


def stream_info(path: Path) -> dict:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-print_format", "json", "-show_streams", "-show_format", path],
        check=True,
        capture_output=True,
    ).stdout
    data = json.loads(out)
    return {**data["streams"][0], "duration": float(data["format"]["duration"])}


def samples(path: Path) -> np.ndarray:
    """Mono 48 kHz float samples of a WAV."""
    out = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", path, "-ac", "1", "-ar", "48000", "-f", "f32le", "-"],
        check=True,
        capture_output=True,
    ).stdout
    return np.frombuffer(out, dtype=np.float32)


def rms_db(x: np.ndarray) -> float:
    return 20 * np.log10(np.sqrt(np.mean(np.square(x, dtype=np.float64))) + 1e-12)


def test_layout_with_transition():
    lay = ClipLayout(100.0, 110.0, fade_s=0.7, transition_s=2.0)
    assert lay.clip_s == pytest.approx(10.0)
    assert (lay.film_offset, lay.outro_offset, lay.total_s) == pytest.approx((1.3, 10.6, 12.6))


def test_layout_without_transition():
    lay = ClipLayout(100.0, 110.0, 0.7, None)
    assert (lay.film_offset, lay.total_s) == pytest.approx((0.0, 10.0))


def test_layout_transition_shorter_than_fade():
    lay = ClipLayout(100.0, 110.0, 0.7, 0.4)
    assert lay.film_offset == 0.0
    assert lay.total_s >= lay.clip_s


def test_filter_plays_transition_twice():
    graph = audio_filter(ClipLayout(2.0, 8.0, 0.7, 1.5), with_transition=True, track=1)
    assert "[0:a:1]" in graph
    assert "asplit" in graph and "amix" in graph and "normalize=0" in graph
    assert "adelay=delays=6100" in graph  # outro at 6.1 s
    assert "atrim=end=7.6" in graph


def test_filter_without_transition_has_no_mix():
    graph = audio_filter(ClipLayout(2.0, 8.0, 0.7, None), with_transition=False, track=0)
    assert "[1:a]" not in graph and "amix" not in graph


def test_render_duration_and_loudness(test_film, transition_wav, tmp_path):
    out = tmp_path / "clip.wav"
    render_audio(test_film, VFF, ClipLayout(2.0, 8.0, 0.7, 1.5), transition_wav, out, S)

    info = stream_info(out)
    assert info["duration"] == pytest.approx(7.6, abs=0.05)
    assert info["sample_rate"] == "48000"
    assert info["channels"] == 2
    assert info["codec_name"] == "pcm_s24le"
    lufs, peak = measure_loudness(out)
    assert -17.0 <= lufs <= -15.0
    assert peak <= -0.9
    assert list(tmp_path.iterdir()) == [out]  # no temporary file left behind


def test_render_no_transition_fades_edges(test_film, tmp_path):
    out = tmp_path / "clip.wav"
    render_audio(test_film, VFF, ClipLayout(2.0, 8.0, 0.7, None), None, out, S)

    x = samples(out)
    assert len(x) / 48000 == pytest.approx(6.0, abs=0.05)
    edge, middle = x[: 48000 // 20], x[len(x) // 2 - 4800 : len(x) // 2 + 4800]
    assert rms_db(middle) - rms_db(edge) >= 20
    assert rms_db(middle) - rms_db(x[-48000 // 20 :]) >= 20


def test_vf_51_is_downmixed_to_stereo(tmp_path):
    film = make_test_film(tmp_path / "film 51.mkv", duration=8.0, vf_channels=6)
    assert probe(film).audio[0].channels == 6
    out = tmp_path / "out" / "clip.wav"
    out.parent.mkdir()
    render_audio(
        film, AudioTrack(0, "fre", "VFF", 6), ClipLayout(1.0, 6.0, 0.7, None), None, out, S
    )

    assert stream_info(out)["channels"] == 2
    lufs, _ = measure_loudness(out)
    assert -17.0 <= lufs <= -15.0


def test_failed_render_leaves_no_file(tmp_path):
    out = tmp_path / "clip.wav"
    with pytest.raises(ClipsError):
        render_audio(tmp_path / "missing.mkv", VFF, ClipLayout(0, 5, 0.7, None), None, out, S)
    assert list(tmp_path.iterdir()) == []
