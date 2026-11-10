import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from podcleaner_clips.adjust import find_fragments
from podcleaner_clips.config import Settings
from podcleaner_clips.media import decode_window
from podcleaner_clips.transcribe import Transcriber, make_transcriber

S = Settings(episodes_dir=Path("episodes"))


@pytest.mark.slow
@pytest.mark.skipif(
    sys.platform != "darwin" or shutil.which("say") is None, reason="needs macOS say"
)
def test_transcribes_french_speech_with_word_times(tmp_path):
    speech = tmp_path / "speech.aiff"
    subprocess.run(
        ["say", "-v", "Thomas", "-o", str(speech), "Bonjour. Il s'appelle Juste Leblanc."],
        check=True,
    )
    audio = decode_window(speech, 0, 0.0, 10.0)

    transcriber = make_transcriber(S.whisper_model)
    words = transcriber.words(audio, offset=100.0)

    assert words
    assert all(w.start >= 100.0 for w in words)
    assert all(a.start <= b.start for a, b in zip(words, words[1:], strict=False))
    match = find_fragments(words, ["juste leblanc"], [], 100.0, 105.0, S)[0]
    assert match is not None and match.score >= 85


def test_make_transcriber_is_lazy():
    # Building the transcriber must not load a model (fast tests stay offline).
    transcriber = make_transcriber("large-v3-turbo")
    assert isinstance(transcriber, Transcriber)
