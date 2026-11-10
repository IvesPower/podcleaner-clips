import json
from pathlib import Path

import pytest

from podcleaner_clips.adjust import Cut
from podcleaner_clips.claude import ClaudeAdvice
from podcleaner_clips.errors import ClipsError
from podcleaner_clips.index import (
    INDEX_NAME,
    ClipEntry,
    FilmIndex,
    file_sha256,
    fingerprint,
    load_index,
    plan_actions,
    save_index,
)
from podcleaner_clips.media import AudioTrack
from podcleaner_clips.notes import ClipNote, split_fragments

RENDER = {"fondu_s": 0.7, "lufs": -16.0}
BOTH = {"audio", "video"}


def note(number: int, start: float, end: float, reference: str) -> ClipNote:
    return ClipNote(number, start, end, reference, split_fragments(reference), number)


def fp(n: ClipNote, transition_sha: str | None = "abc") -> str:
    return fingerprint(
        n, adjust=True, transition=True, track=0, transition_sha=transition_sha, render=RENDER
    )


def fps(notes: list[ClipNote], transition_sha: str | None = "abc") -> dict[int, str]:
    return {n.number: fp(n, transition_sha) for n in notes}


def entry(n: ClipNote, files: dict[str, str] | None = None) -> ClipEntry:
    stem = f"AB-{n.number:02d}"
    return ClipEntry(
        number=n.number,
        reference=n.reference,
        found_fragments=n.fragments,
        fingerprint=fp(n),
        noted_start=n.start,
        noted_end=n.end,
        cut=Cut(n.start - 0.5, n.end + 0.3, "whisper", 96.2, None),
        claude_advice=None,
        duration_s=round(n.end - n.start + 0.8, 3),
        files=files
        if files is not None
        else {"audio": f"audio/{stem}.wav", "video": f"video/{stem}.mp4"},
    )


def index_of(entries: list[ClipEntry]) -> FilmIndex:
    return FilmIndex(
        title="Le Dîner de cons",
        abbreviation="AB",
        film_file="/films/Le Dîner de cons (1998).mkv",
        audio_track=AudioTrack(1, "fre", "VFF", 6),
        claude_advice=[],
        clips=entries,
    )


def touch_files(out_dir: Path, entries: list[ClipEntry]) -> None:
    for e in entries:
        for rel in e.files.values():
            path = out_dir / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"x")


NOTES = [
    note(1, 754.0, 771.0, "il s'appelle Juste Leblanc"),
    note(2, 1200.0, 1215.0, "c'est un con… un vrai"),
    note(3, 1500.0, 1510.0, "le ministre des Finances"),
]


def kinds(actions) -> list[tuple[int, str]]:
    return [(a.number, a.kind) for a in actions]


def test_fingerprint_ignores_the_number_but_not_the_content():
    a, b = note(1, 10.0, 20.0, "bonjour"), note(7, 10.0, 20.0, "bonjour")
    assert fp(a) == fp(b)
    assert fp(a) != fp(note(1, 10.0, 21.0, "bonjour"))
    assert fp(a) != fp(note(1, 10.0, 20.0, "bonsoir"))
    assert fp(a) != fingerprint(
        a, adjust=False, transition=True, track=0, transition_sha="abc", render=RENDER
    )
    assert fp(a) != fingerprint(
        a, adjust=True, transition=True, track=1, transition_sha="abc", render=RENDER
    )
    assert fp(a) != fingerprint(
        a, adjust=True, transition=True, track=0, transition_sha="abc", render={"lufs": -14.0}
    )


def test_file_sha256(tmp_path):
    p = tmp_path / "t.wav"
    p.write_bytes(b"abc")
    assert file_sha256(p) == "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"


def test_first_run_all_new(tmp_path):
    actions, orphans = plan_actions(NOTES, fps(NOTES), None, tmp_path, BOTH)
    assert kinds(actions) == [(1, "nouveau"), (2, "nouveau"), (3, "nouveau")]
    assert all(a.reuse is None and a.rename_from == {} for a in actions)
    assert orphans == []


def test_unchanged_when_same_fingerprint_and_files_exist(tmp_path):
    entries = [entry(n) for n in NOTES]
    touch_files(tmp_path, entries)

    actions, orphans = plan_actions(NOTES, fps(NOTES), index_of(entries), tmp_path, BOTH)

    assert kinds(actions) == [(1, "inchange"), (2, "inchange"), (3, "inchange")]
    assert [a.reuse for a in actions] == entries
    assert orphans == []


def test_changed_line_only_that_clip(tmp_path):
    entries = [entry(n) for n in NOTES]
    touch_files(tmp_path, entries)
    edited = [NOTES[0], note(2, 1200.0, 1218.0, "c'est un con… un vrai"), NOTES[2]]

    actions, _ = plan_actions(edited, fps(edited), index_of(entries), tmp_path, BOTH)

    assert kinds(actions) == [(1, "inchange"), (2, "modifie"), (3, "inchange")]
    assert actions[1].reuse is None


def test_transition_sha_change_invalidates_all(tmp_path):
    entries = [entry(n) for n in NOTES]
    touch_files(tmp_path, entries)

    actions, _ = plan_actions(NOTES, fps(NOTES, "other"), index_of(entries), tmp_path, BOTH)

    assert kinds(actions) == [(1, "modifie"), (2, "modifie"), (3, "modifie")]


def test_deleted_output_file_is_missing_kind(tmp_path):
    entries = [entry(n) for n in NOTES]
    touch_files(tmp_path, entries)
    (tmp_path / entries[1].files["video"]).unlink()

    actions, _ = plan_actions(NOTES, fps(NOTES), index_of(entries), tmp_path, BOTH)

    assert kinds(actions) == [(1, "inchange"), (2, "manquant"), (3, "inchange")]
    assert actions[1].reuse == entries[1]  # the chosen cut is reused for the missing file
    # Only the audio was asked for: the missing video does not matter.
    audio_only, _ = plan_actions(NOTES, fps(NOTES), index_of(entries), tmp_path, {"audio"})
    assert audio_only[1].kind == "inchange"


def test_new_output_kind_wanted_is_missing_kind(tmp_path):
    entries = [entry(n, {"audio": f"audio/AB-{n.number:02d}.wav"}) for n in NOTES]
    touch_files(tmp_path, entries)

    actions, _ = plan_actions(NOTES, fps(NOTES), index_of(entries), tmp_path, BOTH)

    assert {a.kind for a in actions} == {"manquant"}


def test_inserted_line_renames_shifted_clips(tmp_path):
    entries = [entry(n) for n in NOTES]
    touch_files(tmp_path, entries)
    inserted = note(1, 100.0, 110.0, "une nouvelle réplique")
    shifted = [inserted] + [note(n.number + 1, n.start, n.end, n.reference) for n in NOTES]

    actions, orphans = plan_actions(shifted, fps(shifted), index_of(entries), tmp_path, BOTH)

    # Number 1 existed, but its clip moved to 2: the inserted line is new.
    assert kinds(actions) == [(1, "nouveau"), (2, "renomme"), (3, "renomme"), (4, "renomme")]
    assert actions[1].reuse == entries[0]
    assert actions[1].rename_from == {
        "audio": tmp_path / "audio/AB-01.wav",
        "video": tmp_path / "video/AB-01.mp4",
    }
    assert orphans == []


def test_removed_line_reported_as_orphan(tmp_path):
    entries = [entry(n) for n in NOTES]
    touch_files(tmp_path, entries)
    remaining = [NOTES[0], note(2, NOTES[2].start, NOTES[2].end, NOTES[2].reference)]

    actions, orphans = plan_actions(remaining, fps(remaining), index_of(entries), tmp_path, BOTH)

    assert kinds(actions) == [(1, "inchange"), (2, "renomme")]
    assert orphans == [tmp_path / "audio/AB-02.wav", tmp_path / "video/AB-02.mp4"]


def test_orphans_only_list_existing_files(tmp_path):
    entries = [entry(n) for n in NOTES]
    touch_files(tmp_path, entries[:2])  # files of clip 3 already deleted by hand

    _, orphans = plan_actions(NOTES[:2], fps(NOTES[:2]), index_of(entries), tmp_path, BOTH)

    assert orphans == []


def test_identical_lines_each_get_their_own_entry(tmp_path):
    twins = [note(1, 10.0, 20.0, "bonjour"), note(2, 10.0, 20.0, "bonjour")]
    entries = [entry(n) for n in twins]
    touch_files(tmp_path, entries)

    actions, _ = plan_actions(twins, fps(twins), index_of(entries), tmp_path, BOTH)

    assert kinds(actions) == [(1, "inchange"), (2, "inchange")]
    assert [a.reuse for a in actions] == entries


def test_index_roundtrip_utf8(tmp_path):
    advice = ClaudeAdvice("abreviation", "DDC", "Initiales du titre", "claude-haiku-5-5")
    clip = entry(NOTES[0])
    clip = ClipEntry(
        **{**clip.__dict__, "claude_advice": ClaudeAdvice("bornes", "3-41", "Fin de phrase", "m")}
    )
    index = FilmIndex(
        title="Le Dîner de cons",
        abbreviation="DDC",
        film_file="/films/Le Dîner de cons (1998).mkv",
        audio_track=AudioTrack(1, "fre", "Français VFF", 6),
        claude_advice=[advice],
        clips=[clip, entry(NOTES[1])],
    )
    path = tmp_path / "Le Diner de cons" / INDEX_NAME

    save_index(index, path)

    assert load_index(path) == index
    text = path.read_text(encoding="utf-8")
    assert "Le Dîner de cons" in text and "s'appelle Juste Leblanc" in text  # not \u escaped
    data = json.loads(text)
    assert data["version"] == 1
    assert data["film"]["piste_audio"] == {
        "index": 1,
        "langue": "fre",
        "titre": "Français VFF",
        "canaux": 6,
    }
    first = data["extraits"][0]
    assert first["notes"] == {"debut": "00:12:34.000", "fin": "00:12:51.000"}
    assert first["retenu"] == {
        "debut": "00:12:33.500",
        "fin": "00:12:51.300",
        "methode": "whisper",
        "score": 96.2,
        "doute": None,
    }
    assert first["fichiers"] == {"audio": "audio/AB-01.wav", "video": "video/AB-01.mp4"}
    assert [p.name for p in path.parent.iterdir()] == [INDEX_NAME]  # no temporary file left


def test_load_missing_index_is_none(tmp_path):
    assert load_index(tmp_path / INDEX_NAME) is None


def test_load_broken_index_is_an_error(tmp_path):
    path = tmp_path / INDEX_NAME
    path.write_text("{ not json", encoding="utf-8")
    with pytest.raises(ClipsError, match=INDEX_NAME):
        load_index(path)
