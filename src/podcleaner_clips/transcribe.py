"""Word-level transcription of an audio window: mlx-whisper on Apple silicon, faster-whisper
elsewhere."""

import platform
import sys
from typing import Any, Protocol, runtime_checkable

import numpy as np

from podcleaner_clips.adjust import Word

LANGUAGE = "fr"


@runtime_checkable
class Transcriber(Protocol):
    def words(self, audio: np.ndarray, offset: float) -> list[Word]:
        """The words heard in `audio` (mono 16 kHz), times shifted by `offset` seconds."""
        ...


def _words_from(raw: list[tuple[str, float, float]], offset: float) -> list[Word]:
    words = []
    for text, start, end in raw:
        text = text.strip()
        if text:
            words.append(Word(text, round(start + offset, 3), round(end + offset, 3)))
    words.sort(key=lambda w: w.start)
    return words


class _MlxTranscriber:
    def __init__(self, model: str) -> None:
        self.repo = model if "/" in model else f"mlx-community/whisper-{model}"

    def words(self, audio: np.ndarray, offset: float) -> list[Word]:
        import mlx_whisper  # imported late: loading it is slow

        # mlx-whisper keeps the last model in memory, so it is loaded once per run.
        result = mlx_whisper.transcribe(
            audio.astype(np.float32),
            path_or_hf_repo=self.repo,
            language=LANGUAGE,
            word_timestamps=True,
            condition_on_previous_text=False,
        )
        raw = [
            (w["word"], float(w["start"]), float(w["end"]))
            for segment in result.get("segments", [])
            for w in segment.get("words", [])
        ]
        return _words_from(raw, offset)


class _FasterWhisperTranscriber:
    def __init__(self, model: str) -> None:
        self.model_name = model
        self._model: Any = None

    def words(self, audio: np.ndarray, offset: float) -> list[Word]:
        if self._model is None:
            from faster_whisper import WhisperModel  # imported late: loading it is slow

            self._model = WhisperModel(self.model_name, compute_type="int8")
        segments, _ = self._model.transcribe(
            audio.astype(np.float32),
            language=LANGUAGE,
            word_timestamps=True,
            condition_on_previous_text=False,
        )
        raw = [(w.word, float(w.start), float(w.end)) for s in segments for w in (s.words or [])]
        return _words_from(raw, offset)


def make_transcriber(model: str) -> Transcriber:
    """A transcriber for this machine; the model is only loaded on the first call."""
    if sys.platform == "darwin" and platform.machine() == "arm64":
        return _MlxTranscriber(model)
    return _FasterWhisperTranscriber(model)
