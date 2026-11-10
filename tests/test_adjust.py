from pathlib import Path

import pytest

from podcleaner_clips.adjust import (
    Match,
    Word,
    adjust_cut,
    bounds_ok,
    cut_from_words,
    find_fragments,
    sentence_ends,
    sentence_starts,
)
from podcleaner_clips.config import Settings
from podcleaner_clips.subtitles import Anchor

S = Settings(episodes_dir=Path("episodes"))
STEP = 0.35  # one word every 0.35 s
LENGTH = 0.30  # each word lasts 0.30 s: 0.05 s between words of a sentence


def lay(t0: float, text: str) -> list[Word]:
    """The words of `text`, one every STEP seconds from `t0`."""
    return [Word(w, t0 + i * STEP, t0 + i * STEP + LENGTH) for i, w in enumerate(text.split())]


def scene(*lines: tuple[float, str]) -> list[Word]:
    return [w for t0, text in lines for w in lay(t0, text)]


def index_at(words: list[Word], start: float) -> int:
    return next(i for i, w in enumerate(words) if w.start == pytest.approx(start))


def end_of_sentence_at(words: list[Word], t0: float) -> float:
    i = index_at(words, t0)
    while not words[i].text.endswith((".", "!", "?")):
        i += 1
    return words[i].end


def assert_word_bounds(words: list[Word], start: float, end: float) -> None:
    for w in words:
        assert not w.start < start < w.end, f"start cuts {w}"
        assert not w.start < end < w.end, f"end cuts {w}"


# Notes "27:15 ce bébé c'est une connerie 27:37" on a hand-written scene.
BABY = scene(
    (1622.0, "On est où là ?"),
    (1628.0, "Bon écoute-moi bien."),
    (1634.0, "Je vais te dire un truc."),
    (1640.0, "Ce bébé c'est une connerie."),
    (1645.0, "Tu le sais très bien."),
    (1650.0, "Allez on y va maintenant."),
    (1655.0, "Non attends."),
    (1660.0, "Quoi encore ?"),
    (1666.0, "Rien."),
    (1669.0, "Bon."),
)


def test_sentence_starts_and_ends():
    words = scene((0.0, "Salut. Ça va ? Oui"), (5.0, "très bien…"), (6.5, "et toi"))
    # Starts: first word, after "." "?" "…", after a pause of at least 0.6 s.
    assert [words[i].text for i in sentence_starts(words, S)] == [
        "Salut.",
        "Ça",
        "Oui",
        "très",
        "et",
    ]
    assert [words[i].text for i in sentence_ends(words, S)] == [
        "Salut.",
        "?",
        "Oui",
        "bien…",
        "toi",
    ]


def test_scene_kept_with_short_reference():
    decision = adjust_cut(BABY, ["ce bébé c'est une connerie"], [], 1635.0, 1657.0, S)
    cut = decision.cut
    # Start: sentence start closest to 27:15 (27:14); end: sentence end closest to 27:37.
    assert cut.start == pytest.approx(1634.0 - S.pad_before_s)
    assert cut.end == pytest.approx(end_of_sentence_at(BABY, 1655.0) + S.pad_after_s)
    assert cut.method == "whisper" and cut.doubt is None
    assert cut.score is not None and cut.score >= S.score_sure
    assert BABY[decision.first_word].start == pytest.approx(1634.0)
    match = decision.matches[0]
    assert match is not None and BABY[match.first].start == pytest.approx(1640.0)


def test_notes_10s_late_still_snap_to_sentences():
    # The scene really runs 27:14–27:36; the notes say 27:24–27:46.
    decision = adjust_cut(BABY, ["ce bébé c'est une connerie"], [], 1645.0, 1667.0, S)
    first, last = decision.first_word, decision.last_word
    assert first in sentence_starts(BABY, S) and last in sentence_ends(BABY, S)
    match = decision.matches[0]
    assert match is not None and first <= match.first and match.last <= last
    # Starts no later than the fragment's sentence, ends on "Rien." (closest to 27:47).
    assert BABY[first].start <= 1640.0
    assert BABY[last].end == pytest.approx(end_of_sentence_at(BABY, 1666.0))


def test_two_fragments_both_included():
    words = scene(
        (98.0, "Écoute."),
        (102.0, "Si je veux je le fais."),
        (110.0, "Personne ne va me dire le contraire."),
        (125.0, "On en a déjà parlé cent fois."),
        (140.0, "Ta mère est d'accord avec moi."),
        (155.0, "Et ton frère aussi."),
        (165.0, "Il va comprendre ce soir."),
        (172.0, "Crois-moi."),
    )
    decision = adjust_cut(words, ["si je veux", "il va comprendre ce soir"], [], 100.0, 168.0, S)
    assert all(m is not None for m in decision.matches)
    assert decision.cut.start <= 102.0
    assert decision.cut.end >= end_of_sentence_at(words, 165.0)
    assert decision.cut.doubt is None


def test_end_extended_to_include_late_fragment():
    words = scene(
        (100.0, "Tu viens ?"),
        (145.0, "Attends deux secondes."),  # ends at 146.0, right on the noted end
        (150.5, "Je cherche mes clés de voiture."),  # fragment, ends 4 s after the notes
        (158.0, "Voilà."),
    )
    decision = adjust_cut(words, ["je cherche mes clés de voiture"], [], 100.0, 146.0, S)
    fragment_end = end_of_sentence_at(words, 150.5)
    assert decision.cut.end == pytest.approx(fragment_end + S.pad_after_s)


def test_misspelled_reference_found():
    words = scene((10.0, "Franchement tu as été plus solide qu'un roc."), (20.0, "Merci."))
    [match] = find_fragments(words, ["tu as été plus solide qu'un rock"], [], 8.0, 22.0, S)
    assert match is not None and match.score >= S.score_found
    assert words[match.first].text == "tu"


def test_anchor_restricts_search():
    words = scene(
        (108.0, "On va rater le train."),
        (115.0, "Dépêche-toi un peu."),
        (125.0, "On va rater le train."),
    )
    fragment = "on va rater le train"
    [nearest] = find_fragments(words, [fragment], [], 100.0, 130.0, S)
    assert nearest is not None and words[nearest.first].start == pytest.approx(108.0)
    anchor = Anchor(fragment, 125.2, 127.0, 100.0)
    [anchored] = find_fragments(words, [fragment], [anchor], 100.0, 130.0, S)
    assert anchored is not None and words[anchored.first].start == pytest.approx(125.0)


def test_repeated_fragment_without_anchor_is_flagged():
    words = scene(
        (108.0, "On va rater le train."),
        (115.0, "Dépêche-toi un peu."),
        (125.0, "On va rater le train."),
    )
    decision = adjust_cut(words, ["on va rater le train"], [], 100.0, 130.0, S)
    assert decision.cut.doubt is not None and "on va rater le train" in decision.cut.doubt


def test_never_cuts_a_word():
    # Words 0.05 s apart, shorter than both margins: the margins stop at the neighbours.
    words = lay(1620.0, "Il faut. Que tu viennes. " * 30)
    decision = adjust_cut(words, ["que tu viennes"], [], 1635.0, 1657.0, S)
    assert_word_bounds(words, decision.cut.start, decision.cut.end)
    first, last = decision.first_word, decision.last_word
    assert decision.cut.start == pytest.approx(words[first - 1].end)
    assert decision.cut.end == pytest.approx(words[last + 1].start)


def test_cut_from_words_margins():
    words = scene((10.0, "Un deux."), (20.0, "Trois quatre."), (30.0, "Cinq."))
    cut = cut_from_words(words, 2, 3, S)
    assert cut.start == pytest.approx(20.0 - S.pad_before_s)
    assert cut.end == pytest.approx(20.0 + STEP + LENGTH + S.pad_after_s)
    first = cut_from_words(lay(0.05, "Début du film."), 0, 2, S)
    assert first.start == 0.0  # never before the start of the film


def test_unfound_reference_keeps_notes_on_word_bounds():
    words = lay(1620.0, "bla " * 200)
    decision = adjust_cut(words, ["ce bébé c'est une connerie"], [], 1635.1, 1657.0, S)
    cut = decision.cut
    assert cut.method == "notes" and cut.doubt == "reference not found"
    # 1635.1 falls inside the word starting at 1635.05, 1657.0 inside the one ending at 1657.05.
    assert cut.start == pytest.approx(1635.05)
    assert cut.end == pytest.approx(1657.05)
    assert decision.matches == [None]


def test_partially_found_reference_is_flagged():
    decision = adjust_cut(
        BABY, ["ce bébé c'est une connerie", "le chat de la voisine"], [], 1635.0, 1657.0, S
    )
    assert decision.cut.method == "whisper"
    assert decision.matches[1] is None
    assert decision.cut.doubt == "fragment not found: le chat de la voisine"


def test_unsure_reference_is_flagged():
    words = scene((10.0, "Ce bébé ça reste une erreur."), (20.0, "Voilà."))
    decision = adjust_cut(words, ["ce bébé c'est une connerie"], [], 9.0, 21.0, S)
    match = decision.matches[0]
    assert match is not None and S.score_found <= match.score < S.score_sure
    assert decision.cut.doubt == "unsure reference: ce bébé c'est une connerie"


def test_no_sentence_boundary_falls_back_to_nearest_word():
    # No punctuation, no pause, and the transcript starts and ends outside noted ± 15 s.
    words = lay(1599.9, "bla " * 60 + "ce bébé c'est une connerie " + "bla " * 100)
    decision = adjust_cut(words, ["ce bébé c'est une connerie"], [], 1615.0, 1640.0, S)
    assert abs(words[decision.first_word].start - 1615.0) <= STEP / 2
    assert abs(words[decision.last_word].end - 1640.0) <= STEP / 2
    assert "no sentence start" in decision.cut.doubt
    assert "no sentence end" in decision.cut.doubt


def test_short_fragments_are_not_searched_alongside_longer_ones():
    decision = adjust_cut(BABY, ["ce bébé c'est une connerie", "bon"], [], 1635.0, 1657.0, S)
    assert decision.matches[1] is None
    assert decision.cut.doubt is None


def test_bounds_ok_rejects_cut_missing_a_fragment():
    decision = adjust_cut(BABY, ["ce bébé c'est une connerie"], [], 1635.0, 1657.0, S)
    first, last, matches = decision.first_word, decision.last_word, decision.matches
    assert bounds_ok(BABY, first, last, matches, 1635.0, 1657.0, S)
    fragment_start = matches[0].first
    assert not bounds_ok(BABY, first, fragment_start + 1, matches, 1635.0, 1657.0, S)
    assert not bounds_ok(BABY, last, first, matches, 1635.0, 1657.0, S)
    # Start more than 15 s before the noted start.
    assert not bounds_ok(BABY, 0, last, matches, 1645.0, 1657.0, S)


def test_bounds_ok_without_matches():
    assert bounds_ok(BABY, 3, 8, [None], BABY[3].start, BABY[8].end, S)
    assert isinstance(Match("x", 0, 1, 90.0), Match)
