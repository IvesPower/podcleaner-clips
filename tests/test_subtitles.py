from pathlib import Path

import pytest

from podcleaner_clips.config import Settings
from podcleaner_clips.subtitles import Anchor, Cue, find_anchors, normalize, parse_srt

S = Settings(episodes_dir=Path("episodes"))


def test_parse_srt_strips_tags_and_joins_lines():
    text = (
        "1\n"
        "00:00:01,000 --> 00:00:02,500\n"
        "<i>Salut</i>\n"
        "ça va ?\n"
        "\n"
        "2\n"
        "00:00:03,000 --> 00:00:04,000\n"
        '{\\an8}<font color="#ffffff">En haut</font>\n'
    )
    assert parse_srt(text) == [
        Cue(1.0, 2.5, "Salut ça va ?"),
        Cue(3.0, 4.0, "En haut"),
    ]


def test_parse_srt_tolerates_bom_crlf_and_gaps():
    text = (
        "﻿1\r\n"
        "00:00:01,000 --> 00:00:02,000\r\n"
        "Premier\r\n"
        "\r\n"
        "\r\n"
        "\r\n"
        "00:01:02.250 --> 00:01:03,000\r\n"  # no number, dot separator
        "Deuxième\r\n"
        "\r\n"
        "3\r\n"
        "00:01:05,000 --> 00:01:06,000\r\n"  # empty block
        "\r\n"
        "4\r\n"
        "01:00:00,000 --> 01:00:01,000 X1:0 X2:0\r\n"
        "Troisième"
    )
    assert parse_srt(text) == [
        Cue(1.0, 2.0, "Premier"),
        Cue(62.25, 63.0, "Deuxième"),
        Cue(3600.0, 3601.0, "Troisième"),
    ]


def test_normalize():
    assert normalize("  Ce bébé, c'est une CONNERIE… ") == "ce bebe c est une connerie"
    assert normalize("L’œuvre — « là »!") == "l oeuvre la"


def test_anchor_found_despite_approximate_reference():
    cues = [
        Cue(1630.0, 1632.0, "Tu crois ?"),
        Cue(1638.0, 1640.5, "Ce bébé, c'est une connerie."),
        Cue(1641.0, 1643.0, "Je te jure."),
    ]
    anchors = find_anchors(cues, ["ce bebe cest une connerie"], 1635.0, 1657.0, S)
    assert len(anchors) == 1
    anchor = anchors[0]
    assert anchor.fragment == "ce bebe cest une connerie"
    assert (anchor.start, anchor.end) == (1638.0, 1640.5)
    assert anchor.score >= S.score_sure


def test_anchor_limited_to_tolerance_window():
    cues = [Cue(100.0, 102.0, "Ce bébé, c'est une connerie.")]
    # Noted range 155–170: the cue is 40 s before the tolerance window starts.
    assert find_anchors(cues, ["ce bébé c'est une connerie"], 155.0, 170.0, S) == []


def test_anchor_spanning_two_cues():
    cues = [
        Cue(10.0, 11.5, "Je vais te dire,"),
        Cue(11.6, 13.0, "ce bébé, c'est une connerie."),
    ]
    anchors = find_anchors(cues, ["je vais te dire ce bebe c'est une connerie"], 5.0, 20.0, S)
    assert len(anchors) == 1
    assert (anchors[0].start, anchors[0].end) == (10.0, 13.0)
    assert anchors[0].score >= S.score_sure


def test_repeated_line_prefers_closest_to_notes():
    cues = [
        Cue(50.0, 52.0, "On va rater le train."),
        Cue(80.0, 82.0, "On va rater le train."),
        Cue(100.0, 102.0, "On va rater le train."),
    ]
    # Noted range 75–90, midpoint 82.5: the cue at 80 s is the closest.
    anchors = find_anchors(cues, ["on va rater le train"], 75.0, 90.0, S)
    assert [(a.start, a.end) for a in anchors] == [(80.0, 82.0)]


def test_short_cue_does_not_match_long_fragment():
    cues = [
        Cue(20.0, 21.0, "Désolé !"),
        Cue(22.0, 24.0, "Il faut qu'on parle de ta mère."),
    ]
    anchors = find_anchors(cues, ["un juif a encore crucifié le messie"], 15.0, 30.0, S)
    assert anchors == []


def test_one_anchor_per_found_fragment():
    cues = [
        Cue(10.0, 12.0, "Si je veux, je le fais."),
        Cue(40.0, 42.0, "Il va comprendre ce soir."),
    ]
    anchors = find_anchors(
        cues, ["si je veux", "absolument introuvable ici", "il va comprendre ce soir"], 5.0, 50.0, S
    )
    assert [a.fragment for a in anchors] == ["si je veux", "il va comprendre ce soir"]
    assert all(isinstance(a, Anchor) for a in anchors)


@pytest.mark.parametrize("fragment", ["", "   ", "…"])
def test_empty_fragment_gives_no_anchor(fragment):
    cues = [Cue(10.0, 12.0, "Bonjour tout le monde.")]
    assert find_anchors(cues, [fragment], 5.0, 20.0, S) == []
