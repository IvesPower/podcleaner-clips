"""Finding the noted scene in the transcript and snapping its bounds: pure functions."""

from dataclasses import dataclass, replace

from rapidfuzz import fuzz

from podcleaner_clips.config import Settings
from podcleaner_clips.subtitles import Anchor, normalize

# Two matches whose scores are this close are considered equally good.
_TIE_POINTS = 5.0
# With an anchor from the subtitles, the fragment is looked for this close to it.
_ANCHOR_REACH_S = 5.0
_SENTENCE_END = (".", "!", "?", "…")


@dataclass(frozen=True)
class Word:
    text: str
    start: float
    end: float


@dataclass(frozen=True)
class Match:
    fragment: str
    first: int
    last: int
    score: float


@dataclass(frozen=True)
class Cut:
    start: float
    end: float
    method: str  # "notes", "whisper" or "claude"
    score: float | None
    doubt: str | None


@dataclass(frozen=True)
class Decision:
    cut: Cut
    matches: list[Match | None]
    first_word: int | None
    last_word: int | None


@dataclass(frozen=True)
class _Search:
    match: Match | None
    ambiguous: bool


def _text(words: list[Word], first: int, last: int) -> str:
    return normalize(" ".join(w.text for w in words[first : last + 1]))


def _tighten(words: list[Word], target: str, first: int, last: int) -> tuple[int, int]:
    """Drops edge words as long as the window does not get further from the fragment."""
    best = fuzz.ratio(target, _text(words, first, last))
    while first < last:
        for a, b in ((first + 1, last), (first, last - 1)):
            score = fuzz.ratio(target, _text(words, a, b))
            if score >= best:
                best, first, last = score, a, b
                break
        else:
            break
    return first, last


def _overlaps(a: tuple[int, int], b: tuple[int, int]) -> bool:
    return a[0] <= b[1] and b[0] <= a[1]


def _search(
    words: list[Word], fragment: str, anchor: Anchor | None, middle: float, s: Settings
) -> _Search:
    target = normalize(fragment)
    n = len(target.split())
    if anchor is None:
        allowed = range(len(words))
        reference = middle
    else:
        lo, hi = anchor.start - _ANCHOR_REACH_S, anchor.end + _ANCHOR_REACH_S
        allowed = [i for i, w in enumerate(words) if w.start >= lo and w.end <= hi]
        reference = (anchor.start + anchor.end) / 2
    allowed_set = set(allowed)

    # (score, closeness to the fragment, first, last) of every window long enough.
    candidates: list[tuple[float, float, int, int]] = []
    for first in allowed:
        for size in range(max(1, n - 1), n + 3):
            last = first + size - 1
            if last not in allowed_set:
                break
            window = _text(words, first, last)
            if len(window) < len(target):
                continue
            score = fuzz.partial_ratio(target, window)
            if score >= s.score_found:
                candidates.append((score, fuzz.ratio(target, window), first, last))
    if not candidates:
        return _Search(None, False)

    # One match per place in the transcript: the best window, without its extra words.
    candidates.sort(key=lambda c: (-c[0], -c[1]))
    places: list[tuple[tuple[int, int], Match]] = []
    for score, _, first, last in candidates:
        if any(_overlaps((first, last), span) for span, _ in places):
            continue
        a, b = _tighten(words, target, first, last)
        places.append(((first, last), Match(fragment, a, b, score)))

    best = places[0][1].score
    close = [m for _, m in places if m.score >= best - _TIE_POINTS]

    def distance(m: Match) -> float:
        return abs((words[m.first].start + words[m.last].end) / 2 - reference)

    chosen = min(close, key=lambda m: (distance(m), -m.score))
    return _Search(chosen, anchor is None and len(close) > 1)


def _searchable(fragments: list[str]) -> list[bool]:
    """Fragments under 2 words are not searched, unless no fragment has 2 words."""
    long_enough = [len(normalize(f).split()) >= 2 for f in fragments]
    if not any(long_enough):
        return [bool(normalize(f)) for f in fragments]
    return long_enough


def _search_all(
    words: list[Word],
    fragments: list[str],
    anchors: list[Anchor],
    noted_start: float,
    noted_end: float,
    s: Settings,
) -> list[_Search | None]:
    by_fragment = {a.fragment: a for a in anchors}
    middle = (noted_start + noted_end) / 2
    return [
        _search(words, f, by_fragment.get(f), middle, s) if ok else None
        for f, ok in zip(fragments, _searchable(fragments), strict=True)
    ]


def find_fragments(
    words: list[Word],
    fragments: list[str],
    anchors: list[Anchor],
    noted_start: float,
    noted_end: float,
    s: Settings,
) -> list[Match | None]:
    """One result per fragment: where it is in the transcript, None if not found."""
    found = _search_all(words, fragments, anchors, noted_start, noted_end, s)
    return [r.match if r else None for r in found]


def sentence_starts(words: list[Word], s: Settings) -> list[int]:
    """Words that start a sentence: the first, after . ! ? …, or after a pause."""
    return [
        i
        for i, w in enumerate(words)
        if i == 0
        or words[i - 1].text.endswith(_SENTENCE_END)
        or w.start - words[i - 1].end >= s.sentence_gap_s
    ]


def sentence_ends(words: list[Word], s: Settings) -> list[int]:
    """Words that end a sentence: ending with . ! ? …, before a pause, or the last."""
    last = len(words) - 1
    return [
        i
        for i, w in enumerate(words)
        if i == last
        or w.text.endswith(_SENTENCE_END)
        or words[i + 1].start - w.end >= s.sentence_gap_s
    ]


def cut_from_words(words: list[Word], first: int, last: int, s: Settings) -> Cut:
    """Bounds from two word indices, with margins that never reach into a neighbour word."""
    start = words[first].start - s.pad_before_s
    if first > 0:
        start = max(start, words[first - 1].end)
    end = words[last].end + s.pad_after_s
    if last + 1 < len(words):
        end = min(end, words[last + 1].start)
    return Cut(max(0.0, start), end, "whisper", None, None)


def bounds_ok(
    words: list[Word],
    first: int,
    last: int,
    matches: list[Match | None],
    noted_start: float,
    noted_end: float,
    s: Settings,
) -> bool:
    """Start and end within tolerance of the notes, every found fragment inside."""
    if not 0 <= first <= last < len(words):
        return False
    if abs(words[first].start - noted_start) > s.tolerance_s:
        return False
    if abs(words[last].end - noted_end) > s.tolerance_s:
        return False
    return all(first <= m.first and m.last <= last for m in matches if m is not None)


def _outward_to_words(words: list[Word], start: float, end: float) -> tuple[float, float]:
    """Moves each noted timecode out of the word it falls in, if any."""
    for w in words:
        if w.start < start < w.end:
            start = w.start
        if w.start < end < w.end:
            end = w.end
    return start, end


def _closest(indices: list[int], time_of, target: float) -> int | None:
    return min(indices, key=lambda i: abs(time_of(i) - target), default=None)


def adjust_cut(
    words: list[Word],
    fragments: list[str],
    anchors: list[Anchor],
    noted_start: float,
    noted_end: float,
    s: Settings,
) -> Decision:
    """The clip bounds: sentence boundaries near the notes, with every found fragment inside.

    `words` covers [noted_start - tolerance_s, noted_end + tolerance_s].
    """
    searches = _search_all(words, fragments, anchors, noted_start, noted_end, s)
    matches = [r.match if r else None for r in searches]
    found = [m for m in matches if m is not None]
    if not found:
        start, end = _outward_to_words(words, noted_start, noted_end)
        cut = Cut(start, end, "notes", None, "reference not found")
        return Decision(cut, matches, None, None)

    doubts: list[str] = []
    tol = s.tolerance_s
    frag_first = min(m.first for m in found)
    frag_last = max(m.last for m in found)

    starts = [
        i
        for i in sentence_starts(words, s)
        if i <= frag_first and abs(words[i].start - noted_start) <= tol
    ]
    first = _closest(starts, lambda i: words[i].start, noted_start)
    if first is None:
        first = _closest(list(range(frag_first + 1)), lambda i: words[i].start, noted_start)
        doubts.append("no sentence start near the noted timecode")

    ends = [
        i
        for i in sentence_ends(words, s)
        if i >= frag_last and abs(words[i].end - noted_end) <= tol
    ]
    last = _closest(ends, lambda i: words[i].end, noted_end)
    if last is None:
        last = _closest(list(range(frag_last, len(words))), lambda i: words[i].end, noted_end)
        doubts.append("no sentence end near the noted timecode")

    for fragment, search in zip(fragments, searches, strict=True):
        if search is None:
            continue
        if search.match is None:
            doubts.append(f"fragment not found: {fragment}")
        elif search.match.score < s.score_sure:
            doubts.append(f"unsure reference: {fragment}")
        elif search.ambiguous:
            doubts.append(f"ambiguous reference: {fragment}")

    cut = replace(
        cut_from_words(words, first, last, s),
        score=min(m.score for m in found),
        doubt="; ".join(doubts) or None,
    )
    return Decision(cut, matches, first, last)
