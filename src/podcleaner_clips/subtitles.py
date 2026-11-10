"""Subtitle reading and reference spotting in subtitles: pure functions, no disk access."""

import re
from dataclasses import dataclass

from rapidfuzz import fuzz

from podcleaner_clips.config import Settings
from podcleaner_clips.naming import strip_accents

_TIME = r"(\d+):(\d{1,2}):(\d{1,2})(?:[,.](\d{1,3}))?"
_TIMING = re.compile(rf"{_TIME}\s*-->\s*{_TIME}")
_BLANK_LINE = re.compile(r"\n\s*\n")
_TAG = re.compile(r"<[^>]*>|\{[^}]*\}")
_NOT_ALNUM = re.compile(r"[^0-9a-z]+")
_SPACES = re.compile(r"\s+")

# Two candidates whose scores are this close are considered equally good.
_TIE_POINTS = 5.0


@dataclass(frozen=True)
class Cue:
    start: float
    end: float
    text: str


@dataclass(frozen=True)
class Anchor:
    fragment: str
    start: float
    end: float
    score: float


def _seconds(hours: str, minutes: str, secs: str, millis: str | None) -> float:
    ms = int((millis or "0").ljust(3, "0"))
    return int(hours) * 3600 + int(minutes) * 60 + int(secs) + ms / 1000


def _clean(text: str) -> str:
    return _SPACES.sub(" ", _TAG.sub("", text)).strip()


def parse_srt(text: str) -> list[Cue]:
    """Cues of an SRT text; tolerates a BOM, CRLF, missing numbers and empty blocks."""
    text = text.lstrip("﻿").replace("\r\n", "\n").replace("\r", "\n")
    cues: list[Cue] = []
    for block in _BLANK_LINE.split(text):
        lines = block.strip("\n").split("\n")
        for i, line in enumerate(lines):
            timing = _TIMING.search(line)
            if timing is None:
                continue
            body = _clean(" ".join(lines[i + 1 :]))
            if body:
                groups = timing.groups()
                cues.append(Cue(_seconds(*groups[:4]), _seconds(*groups[4:]), body))
            break
    return cues


def normalize(text: str) -> str:
    """Lowercase, no accents, punctuation and apostrophes as spaces, spaces collapsed."""
    return _NOT_ALNUM.sub(" ", strip_accents(text).lower()).strip()


def _best_anchor(
    cues: list[Cue], fragment: str, lo: float, hi: float, middle: float, s: Settings
) -> Anchor | None:
    target = normalize(fragment)
    if not target:
        return None
    candidates: list[Anchor] = []
    for i, cue in enumerate(cues):
        if not lo <= cue.start <= hi:
            continue
        # Join the following cues until the window is at least as long as the fragment,
        # so that a short cue never matches a long fragment on its own.
        window, j = normalize(cue.text), i
        while len(window) < len(target) and j + 1 < len(cues):
            j += 1
            window = f"{window} {normalize(cues[j].text)}".strip()
        if len(window) < len(target):
            continue
        score = fuzz.partial_ratio(target, window)
        if score >= s.score_found:
            candidates.append(Anchor(fragment, cue.start, cues[j].end, score))
    if not candidates:
        return None
    best = max(a.score for a in candidates)
    close = [a for a in candidates if a.score >= best - _TIE_POINTS]
    return min(close, key=lambda a: (abs((a.start + a.end) / 2 - middle), -a.score))


def find_anchors(
    cues: list[Cue],
    fragments: list[str],
    noted_start: float,
    noted_end: float,
    s: Settings,
) -> list[Anchor]:
    """The best subtitle match of each fragment near the noted range.

    Fragments with no match scoring at least `score_found` are left out.
    """
    lo, hi = noted_start - s.tolerance_s, noted_end + s.tolerance_s
    middle = (noted_start + noted_end) / 2
    anchors = (_best_anchor(cues, f, lo, hi, middle, s) for f in fragments)
    return [a for a in anchors if a is not None]
