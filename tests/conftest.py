import subprocess
import sys
from pathlib import Path

import pytest

# Lets tests import the helper scripts (make_test_film) like a module.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from make_test_film import make_test_film  # noqa: E402


@pytest.fixture(scope="session")
def test_film(tmp_path_factory) -> Path:
    """12 s test film: VFF, VO and VFQ tracks, cover art, no subtitles."""
    return make_test_film(tmp_path_factory.mktemp("film") / "test film.mkv")


@pytest.fixture(scope="session")
def transition_wav(tmp_path_factory) -> Path:
    """1.5 s stereo transition sound (44.1 kHz, to check resampling)."""
    out = tmp_path_factory.mktemp("transition") / "transition.wav"
    subprocess.run(
        [
            "ffmpeg", "-v", "error", "-y",
            "-f", "lavfi", "-i", "sine=frequency=330:duration=1.5:sample_rate=44100",
            "-ac", "2", str(out),
        ],
        check=True,
    )  # fmt: skip
    return out


@pytest.fixture(autouse=True)
def _no_claude_code(monkeypatch):
    """Fast tests never start the real Claude Code CLI, even where it is installed."""
    monkeypatch.setattr("podcleaner_clips.claude.find_cli", lambda: None)


def _transition_video(path: Path, colour: str) -> Path:
    """0.6 s square video in one colour, with its own 1 kHz sound (never to be heard)."""
    subprocess.run(
        [
            "ffmpeg", "-v", "error", "-y",
            "-f", "lavfi", "-i", f"color=c={colour}:s=120x120:d=0.6:r=30",
            "-f", "lavfi", "-i", "sine=frequency=1000:duration=0.6",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(path),
        ],
        check=True,
    )  # fmt: skip
    return path


@pytest.fixture(scope="session")
def transition_mp4(tmp_path_factory) -> Path:
    return _transition_video(tmp_path_factory.mktemp("tvideo") / "intro.mp4", "red")


@pytest.fixture(scope="session")
def other_transition_mp4(tmp_path_factory) -> Path:
    return _transition_video(tmp_path_factory.mktemp("tvideo2") / "intro.mp4", "blue")
