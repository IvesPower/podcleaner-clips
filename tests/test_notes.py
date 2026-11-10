from pathlib import Path

import pytest

from podcleaner_clips.errors import ClipsError
from podcleaner_clips.notes import read_notes, split_fragments, write_abbreviation

# Real format of notes taken while watching a film (neutral content).
REAL = """\
2:35 d'une soirée incroyable 2:51

6;25 si tu n'es pas d'accord tu es quoi ? 6:40

25 min 30 : ça va te remettre les idées en place 25:40

43:00 si je veux … il va comprendre ce soir 44:08

1:16:55 l'histoire se répète - encore une fois 1:17;08
Notes libres : la scène du taxi est trop longue.
"""

LEGACY = """\
# Le Dîner de cons
fichier: Le Diner de cons (1998).mkv
abreviation: DDC

## Extraits
- 00:12:34 > 00:12:51 | Il s'appelle Juste Leblanc
- 00:47:02 > 00:47:20 | Il a une bonne tête de vainqueur

## Notes libres
La scène du téléphone est trop longue pour un extrait.
"""


def write(tmp_path: Path, text: str, name: str = "notes.md") -> Path:
    path = tmp_path / name
    path.write_bytes(text.encode("utf-8"))
    return path


def test_reads_real_world_lines(tmp_path):
    n = read_notes(write(tmp_path, REAL))
    assert n.title is None and n.film_file is None and n.abbreviation is None
    assert [(c.number, c.start, c.end) for c in n.clips] == [
        (1, 155.0, 171.0),
        (2, 385.0, 400.0),
        (3, 1530.0, 1540.0),
        (4, 2580.0, 2648.0),
        (5, 4615.0, 4628.0),
    ]
    assert n.clips[0].reference == "d'une soirée incroyable"
    assert n.clips[2].reference == "ça va te remettre les idées en place"  # ":" removed
    assert n.clips[3].fragments == ["si je veux", "il va comprendre ce soir"]
    assert n.clips[4].fragments == ["l'histoire se répète", "encore une fois"]
    assert n.clips[0].fragments == ["d'une soirée incroyable"]
    assert [c.source_line for c in n.clips] == [1, 3, 5, 7, 9]
    assert n.errors == []


def test_reads_legacy_format_with_header(tmp_path):
    n = read_notes(write(tmp_path, LEGACY))
    assert n.title == "Le Dîner de cons"
    assert n.film_file == "Le Diner de cons (1998).mkv"
    assert n.abbreviation == "DDC"
    assert [(c.number, c.start, c.end) for c in n.clips] == [(1, 754.0, 771.0), (2, 2822.0, 2840.0)]
    assert n.clips[0].reference == "Il s'appelle Juste Leblanc"


def test_header_keys_are_flexible(tmp_path):
    text = "# Titre\nFichier :  film.mkv \nabréviation: tnb\n2:35 a b 2:51\n"
    n = read_notes(write(tmp_path, text))
    assert (n.film_file, n.abbreviation) == ("film.mkv", "TNB")


def test_bulleted_real_format_is_accepted(tmp_path):
    n = read_notes(write(tmp_path, "- 2:35 une réplique 2:51\n* 3:00 une autre 3:10\n"))
    assert [c.reference for c in n.clips] == ["une réplique", "une autre"]


def test_reference_containing_numbers_keeps_them(tmp_path):
    n = read_notes(write(tmp_path, "10:00 il est 3 heures du matin 10:20\n"))
    assert n.clips[0].reference == "il est 3 heures du matin"


def test_split_fragments():
    assert split_fragments("peut-être pas") == ["peut-être pas"]
    assert split_fragments("a b ... c d") == ["a b", "c d"]
    assert split_fragments("a b…c d") == ["a b", "c d"]
    assert split_fragments("a b – c d") == ["a b", "c d"]  # en dash
    assert split_fragments("  seul  ") == ["seul"]
    assert split_fragments("… a b …") == ["a b"]


@pytest.mark.parametrize(
    "line", ["2:35 sans fin", "rien 2:51", "Notes libres : la scène", "## Extraits", "2:35"]
)
def test_ignores_lines_without_both_timecodes(tmp_path, line):
    n = read_notes(write(tmp_path, line + "\n"))
    assert n.clips == [] and n.errors == []


def test_bom_and_crlf(tmp_path):
    n = read_notes(write(tmp_path, "﻿2:35 a b 2:51\r\n3:00 c d 3:10\r\n"))
    assert [(c.start, c.reference) for c in n.clips] == [(155.0, "a b"), (180.0, "c d")]


def test_start_after_end_is_reported_not_fatal(tmp_path):
    n = read_notes(write(tmp_path, "2:51 inversée 2:35\n3:00 correcte 3:10\n"))
    assert [(c.number, c.reference) for c in n.clips] == [(2, "correcte")]
    assert len(n.errors) == 1 and n.errors[0].startswith("Line 1:")


def test_empty_reference_is_an_error(tmp_path):
    n = read_notes(write(tmp_path, "2:35 2:51\n"))
    assert n.clips == []
    assert len(n.errors) == 1 and "Line 1" in n.errors[0]


def test_missing_file_is_a_clips_error(tmp_path):
    with pytest.raises(ClipsError, match="not found"):
        read_notes(tmp_path / "absent.md")


def test_write_abbreviation_after_fichier_keeps_rest_byte_for_byte(tmp_path):
    original = "# Titre\r\nfichier: film.mkv\r\n\r\n2:35 a b 2:51\r\n"
    path = write(tmp_path, original)
    write_abbreviation(path, "TNB")
    assert path.read_bytes() == (
        b"# Titre\r\nfichier: film.mkv\r\nabreviation: TNB\r\n\r\n2:35 a b 2:51\r\n"
    )


def test_write_abbreviation_after_title_or_at_top(tmp_path):
    path = write(tmp_path, "# Titre\n2:35 a b 2:51\n")
    write_abbreviation(path, "AB")
    assert path.read_text(encoding="utf-8") == "# Titre\nabreviation: AB\n2:35 a b 2:51\n"

    path = write(tmp_path, "﻿2:35 a b 2:51", name="sans-en-tete.md")
    write_abbreviation(path, "AB")
    assert path.read_bytes() == "﻿abreviation: AB\n2:35 a b 2:51".encode()


def test_write_abbreviation_replaces_existing_value(tmp_path):
    path = write(tmp_path, LEGACY)
    write_abbreviation(path, "DDC2")
    assert read_notes(path).abbreviation == "DDC2"
    assert path.read_text(encoding="utf-8") == LEGACY.replace(
        "abreviation: DDC", "abreviation: DDC2"
    )
