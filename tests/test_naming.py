import pytest
from podcleaner_clips.naming import (
    clip_basename,
    fallback_abbreviation,
    film_folder_name,
    format_tc,
    parse_tc,
    slugify,
    strip_accents,
)

WINDOWS_FORBIDDEN = set('<>:"/\\|?*')
WORDS = "un deux trois quatre cinq six sept huit neuf dix onze"


def test_parse_tc_variants():
    assert parse_tc("00:12:34") == 754.0
    assert parse_tc("0:12:34.5") == 754.5
    assert parse_tc("00:12:34,250") == 754.25
    assert parse_tc(" 01:00:00 ") == 3600.0


@pytest.mark.parametrize(
    "bad", ["12:34", "00:12:34.1234", "00:61:00", "00:00:60", "aa:bb:cc", "", "-0:00:01"]
)
def test_parse_tc_rejects_malformed(bad):
    with pytest.raises(ValueError):
        parse_tc(bad)


def test_format_tc():
    assert format_tc(0) == "00:00:00.000"
    assert format_tc(754.25) == "00:12:34.250"
    assert format_tc(7803.4567) == "02:10:03.457"


def test_format_tc_rejects_negative():
    with pytest.raises(ValueError):
        format_tc(-1.0)


def test_format_then_parse_roundtrip():
    assert parse_tc(format_tc(2822.125)) == 2822.125


def test_strip_accents():
    assert strip_accents("Dîner Ça été Œuf æ") == "Diner Ca ete OEuf ae"


def test_slugify_spec_examples():
    assert slugify("Il s'appelle Juste Leblanc") == "il-s-appelle-juste-leblanc"
    assert slugify("Il a une bonne tête de vainqueur") == "il-a-une-bonne-tete-de-vainqueur"
    assert slugify("Ça, c'est l'été !") == "ca-c-est-l-ete"
    assert slugify("Œuf : « oui » / non ?") == "oeuf-oui-non"
    assert slugify("Il s’appelle") == "il-s-appelle"  # apostrophe typographique
    assert slugify("!!!") == "extrait"


def test_slugify_cuts_on_word_boundary():
    s = slugify(WORDS)
    assert s == "un-deux-trois-quatre-cinq-six-sept-huit"
    assert len(s) <= 40


def test_slugify_truncates_a_single_overlong_word():
    assert slugify("a" * 60) == "a" * 40


def test_fallback_abbreviation():
    assert fallback_abbreviation("Le Dîner de cons") == "DDC"
    assert fallback_abbreviation("L'Auberge espagnole") == "AE"
    assert fallback_abbreviation("Alien") == "AL"  # un seul mot : deux premières lettres
    assert fallback_abbreviation("The Big Lebowski") == "BL"


def test_fallback_abbreviation_is_2_to_6_chars():
    long = fallback_abbreviation("Le bon la brute et le truand du far west")
    assert long == "BLBELT"
    assert fallback_abbreviation("La") == "LA"  # article seul : on le garde
    assert fallback_abbreviation("!!!") == "FILM"


def test_film_folder_name_is_windows_safe():
    assert film_folder_name("Le Dîner de cons") == "Le Diner de cons"
    assert film_folder_name("Mission: Impossible?") == "Mission Impossible"
    assert film_folder_name('A/B\\C<D>E|F*G"H') == "A B C D E F G H"
    assert film_folder_name("Fin. ") == "Fin"  # Windows refuse point ou espace final
    assert film_folder_name("???") == "Film"


def test_film_folder_name_avoids_windows_reserved_names():
    assert film_folder_name("Con") == "Con_"
    assert film_folder_name("nul") == "nul_"
    assert film_folder_name("Con Air") == "Con Air"


def test_clip_basename():
    assert (
        clip_basename("DDC", 1, "Il s'appelle Juste Leblanc") == "DDC-01-il-s-appelle-juste-leblanc"
    )
    assert clip_basename("DDC", 12, "!!!") == "DDC-12-extrait"


def test_generated_names_have_no_windows_forbidden_chars():
    tricky = 'Quoi ?! « Non » : <oui> | "peut-être" / \\ *'
    for name in (slugify(tricky), film_folder_name(tricky), clip_basename("X", 3, tricky)):
        assert not WINDOWS_FORBIDDEN & set(name), name
        assert name.isascii(), name
