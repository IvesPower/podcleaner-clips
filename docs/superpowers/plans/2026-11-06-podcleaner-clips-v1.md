# Podcleaner-clips v1: implementation plan

[Français](2026-11-06-podcleaner-clips-v1.fr.md) · **English** — translated from the French original. User-facing strings (messages, config keys, index keys, test data) stay in French, because the tool's interface is French.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** a `podcleaner-clips run notes.md` CLI that reads a film's notes file (approximate timecodes and partial references), finds each noted scene with the subtitles and Whisper, snaps its bounds to sentence boundaries, then writes the audio (WAV) and video (MP4) clips with fades, transition sound and normalization, plus the `extraits.json` index.

**Architecture:** Python package `src/podcleaner_clips/`. ffmpeg/ffprobe, Whisper and Claude stay at the edges, behind narrow functions; everything that decides (reading notes, track choice, locating references, cut snapping, clip time layout, fingerprints) is made of pure functions testable without media. A clip is rendered once as a normalized WAV; the MP4 reuses that WAV as its soundtrack.

**Tech Stack:** Python 3.11–3.12, uv, Typer, platformdirs, rapidfuzz, numpy, mlx-whisper (macOS arm64) / faster-whisper (elsewhere), anthropic, ffmpeg/ffprobe (PATH), pytest, Ruff.

**Spec:** `docs/spec.fr.md` (original) · `docs/spec.md` (English translation). Sibling project for conventions: `../podcleaner-editor/docs/superpowers/plans/2026-11-05-m1-fondations-analyse.md`.

## Global Constraints

- Runs on macOS and Windows; paths via `pathlib`, no hard-coded path, text files read and written with `encoding="utf-8"`.
- No account or API key required: without `ANTHROPIC_API_KEY`, every Claude call has a fallback (title initials, simple rule for bounds).
- Inputs: `.mkv`, `.avi`, `.mp4`.
- Always a VF (French dub) audio track, VFF preferred when there is also a VFQ (configurable); if no track is tagged French, the first one, with a warning.
- Real notes: a clip line = start timecode, reference, end timecode. Approximate timecodes (~10 s off); reference = a few words, not necessarily exact, possibly several fragments.
- The clip keeps the noted scene: start and end snapped to sentence boundaries within ±15 s of the noted timecodes, never in the middle of a word, every found reference included; better some margin than a cut-off line.
- Locating: French text subtitles if any (other than "forced"), then Whisper; cuts are always made on the dub's words transcribed by Whisper.
- Accepted timecodes: `HH:MM:SS` or `MM:SS` (`45:12` = 45 min 12 s), optional decimals; `6;25` and `25 min 30` tolerated.
- A full film is never transcribed: only the noted scene ±15 s.
- Fades: 0.7 s at the start and the end.
- Audio: 48 kHz WAV, -16 LUFS integrated, -1 dBTP.
- Video: H.264 + AAC MP4, same cut and same sound as the audio; black screen during the transition sound.
- Naming: `{abbreviation}-{2-digit number}-{first-words-of-the-reference}.{wav|mp4}`.
- Output: `{dossier_episodes}/{film-name}/audio/`, `…/video/`, `…/extraits.json`.
- A new run only rewrites the clips that were added or changed.
- Out of scope for v1: live player, video transition effects, burning subtitles into clips.
- Code and output in English: identifiers, comments, docstrings, displayed messages, errors, CLI help; messages quoted in French in the tasks below are to be written in English. Kept in French: config file and index keys.
- Fast tests (`pytest -m "not slow"`) without a Whisper model or network; they may call ffmpeg. Tests that load Whisper are marked `slow`.
- `main` is protected: each task is done on a branch (`feat/…`, `fix/…`, `docs/…`, `chore/…`) and lands through a pull request. Commits follow Conventional Commits, title in English then French (`type: English / français`); the commit messages given in the tasks below only show the French part, to be completed. PR title and description: English then French (see `CONTRIBUTING.md`).
- Docs in English (`*.md`) and French (`*.fr.md`): any change to one updates the other in the same PR. `CLAUDE.md` is in French.

## Decisions made by this plan (not fixed by the spec)

| Topic | Decision |
| --- | --- |
| Package / command | `podcleaner_clips` / `podcleaner-clips` (`run`, `config init`, `config show`, `version`) |
| Configuration | TOML in `platformdirs.user_config_dir("podcleaner-clips")/config.toml`, overridable with `--config` or `PODCLEANER_CLIPS_CONFIG` |
| Film title | The notes file's `# ` heading; otherwise the film's file name up to and including the year in parentheses (`The Night Before (2015) Bluray-1080p.mkv` → `The Night Before (2015)`), otherwise its name without extension |
| Film folder | Title without accents or `<>:"/\|?*`, at most 60 characters (`Le Dîner de cons` → `Le Diner de cons`), to avoid NFC/NFD issues between Mac and Windows |
| Slug | From the reference: lowercase, no accents, apostrophes and punctuation → `-`, whole words up to 40 characters; empty → `extrait` |
| Fallback abbreviation | Drop the leading article (le, la, les, l', un, une, des, the, a, an), uppercase initials of the remaining words, 2 to 6 characters (`Le Dîner de cons` → `DDC`) |
| Number | Order of the line in the notes file, starting at 1 |
| Fragments | The reference is split on `…`, `...` and ` - `; fragments shorter than 2 words are ignored for searching |
| Fuzzy search | Per fragment, after normalization (lowercase, no accents or punctuation): the fragment is compared to a text window **at least as long as itself** (consecutive transcription words, or consecutive subtitles joined) with `rapidfuzz.fuzz.partial_ratio`; found if score ≥ 70, sure if ≥ 85. Without this length condition, a short subtitle ("Désolé !") scored 85 against a long reference. Measured on the test film: 5 fragments out of 10 found in the subtitles, with no false positive; the others differ too much from the dub and rely on Whisper |
| Subtitles | A French text subtitle track (`subrip`, `ass`, `ssa`, `mov_text`, `webvtt`), excluding titles containing "forcé" / "forced"; "complet" / "full" / "SDH" preferred. Extracted once per run as SRT. A subtitle hit sets an anchor: the fragment is then searched in the transcription within ±5 s of that anchor |
| Bounds without Claude | Start: sentence start closest to `noted_start` in `[noted_start − 15, first fragment]`; end: sentence end closest to `noted_end` in `[last fragment, noted_end + 15]`. Sentence start = first word, word after `.`, `!`, `?`, `…`, or after a pause ≥ 0.6 s. No sentence boundary: closest word boundary, flagged |
| Claude's role on cuts | With a key and adjustment on, Claude picks the bounds of **every** clip (start and end words) from the transcription, the found fragments and the heuristic proposal. Answer checked: start within `noted_start ± 15`, end within `noted_end ± 15`, every found fragment included; otherwise the heuristic proposal is kept |
| Doubt | Fragment not found (score < 70) or found but not sure (< 85), or two occurrences within 5 points: flagged in the summary and the index. No fragment found: noted timecodes, widened to word boundaries |
| Dub | `doublage_prefere = "VFF"` (or `"VFQ"`). VFQ recognized if the track title contains `VFQ`, `Québec`, `Quebec` or `Canad`, or if the language is `fr-CA`; VFF if `VFF`, `France` or plain `VF` |
| Channels | Stereo output; a 5.1 VF is downmixed to stereo by ffmpeg, keeping the center (dialogue) channel |
| Transition placement | Film sound starts `transition − 0.7 s` after the beginning and fades in over 0.7 s; the closing transition starts when the fade-out starts. Same sound file for intro and outro |
| Picture during the transition | Black as long as the film sound has not started (and after it stops), so the picture stays in sync with the sound |
| WAV bit depth | 24-bit |
| Models | Whisper `large-v3-turbo` (mlx: `mlx-community/whisper-large-v3-turbo`), language `fr`; Claude `claude-haiku-5-5`; both configurable |
| Clips removed from the notes | Their files are not deleted, only listed as "orphans" in the summary |

## Review Focus

1. **Real-world notes file** (from real notes): `TC reference TC` lines without bullets, `6;25`, `25 min 30 :`, `1:17;08`, UTF-8 BOM, Windows line endings, no header, start ≥ end. Valid lines must be read; a line with start ≥ end is an error reported for that clip without stopping the others. Tests in task 3.
2. **Approximate reference and shifted timing**: a misspelled 3-word reference, timecodes 10 s off, two fragments separated by `…` over a one-minute scene. The scene must be found and contain every fragment. Tests in task 6.
3. **5.1 VF with both VFF and VFQ** (the test film's case): VFF is chosen, the clip comes out in stereo, dialogue audible, at the right level. Tests in tasks 5 and 8.
4. **Anamorphic video, 23.976 fps, 10-bit HEVC, `mjpeg` cover as a video stream**: the black segments and the film picture concatenate without ffmpeg errors and come out as yuv420p; the cover is ignored. Tests in tasks 5 and 9.
5. **Rerun after an edit**: changing one reference only redoes that clip; changing the transition sound redoes everything; deleting an output file redoes it; inserting a line renames the shifted files instead of recomputing them. Tests in task 10.

---

## Files

```
pyproject.toml, uv.lock, CLAUDE.md
.gitignore, LICENSE, README(.fr).md, CONTRIBUTING(.fr).md, .github/CODEOWNERS   (already present)
.github/workflows/ci.yml
.claude/hooks/python_checks.py           (modified: runs through uv run)
.claude/skills/test-rapide/SKILL.md
.claude/skills/compat-windows/SKILL.md
scripts/make_test_film.py                test film (VFF + VFQ + original, French subtitles), used by tests and the skill
scripts/check_windows_compat.py
src/podcleaner_clips/__init__.py         __version__
src/podcleaner_clips/cli.py              Typer app: version, config, run
src/podcleaner_clips/errors.py           ClipsError (user message, exit code 2)
src/podcleaner_clips/naming.py           timecodes, slug, fallback abbreviation, file names
src/podcleaner_clips/notes.py            reading the notes file, fragments, writing the abbreviation
src/podcleaner_clips/config.py           Settings + TOML loading
src/podcleaner_clips/media.py            ffmpeg presence, ffprobe, track choice, window decoding, subtitle extraction
src/podcleaner_clips/subtitles.py        SRT parsing and locating fragments in subtitles (pure)
src/podcleaner_clips/adjust.py           Word, locating fragments, snapping bounds (pure)
src/podcleaner_clips/transcribe.py       transcription of a window (mlx / faster-whisper)
src/podcleaner_clips/claude.py           abbreviation and bounds choice, with fallbacks
src/podcleaner_clips/render_audio.py     time layout, mix, loudnorm
src/podcleaner_clips/render_video.py     black + film picture + soundtrack
src/podcleaner_clips/index.py            extraits.json, fingerprints, render plan
src/podcleaner_clips/pipeline.py         end-to-end run + summary
tests/conftest.py                        fixtures: test film, transition sound
tests/test_<module>.py                   one file per module
```

---

### Task 1: repository foundation and minimal CLI

**Files:**
- Create: `pyproject.toml`, `CLAUDE.md`, `.github/workflows/ci.yml`, `src/podcleaner_clips/__init__.py`, `src/podcleaner_clips/cli.py`, `src/podcleaner_clips/errors.py`, `tests/test_cli.py`
- Modify: `.claude/hooks/python_checks.py`, `.gitignore` (already in the repo, extend if needed)

**Interfaces:**
- Produces: `podcleaner_clips.__version__ = "0.1.0"`; `podcleaner_clips.cli.app: typer.Typer`; `class ClipsError(Exception)` whose message is shown as is (`Erreur : …` on stderr), exit code 2, no Python traceback.

- [ ] **Step 1:** `brew install uv` (system Python is 3.9), branch `chore/project-setup`, `uv init --package --python 3.12` (without overwriting README, LICENSE or `.gitignore`, already present). `pyproject.toml`: `requires-python = ">=3.11,<3.13"`, script `podcleaner-clips = "podcleaner_clips.cli:main"`, dependencies `typer`, `platformdirs`, `rapidfuzz`, `numpy`, `anthropic`, `mlx-whisper ; sys_platform == 'darwin' and platform_machine == 'arm64'`, `faster-whisper ; sys_platform != 'darwin' or platform_machine != 'arm64'`; dev group `pytest`, `ruff`. Ruff `line-length = 100`, rules `E,F,I,UP,B`. pytest: `markers = ["slow: charge un modèle Whisper"]`, `addopts = "-m 'not slow'"`.
- [ ] **Step 2:** `.gitignore` already exists: check that `tests/` produces no versioned media file (test films are created in `tmp_path`).
- [ ] **Step 3: failing tests**

```python
def test_version_command_prints_version():
    result = CliRunner().invoke(app, ["version"])
    assert result.exit_code == 0 and "0.1.0" in result.output

def test_clips_error_exits_2_with_message():
    # test command that raises ClipsError("Fichier introuvable : x.mkv")
    # → exit_code == 2, "Erreur : Fichier introuvable : x.mkv" in the output, no "Traceback"
```

- [ ] **Step 4:** `uv run pytest` → FAIL (module missing).
- [ ] **Step 5:** implement `cli.py` (`app`, `version` command, `main()` that calls `app` and turns `ClipsError` into a message + code 2) and `errors.py`.
- [ ] **Step 6:** `uv run pytest` → PASS.
- [ ] **Step 7:** hook: if `uv.lock` exists at the root, prefix ruff and pytest with `uv run` and run `pytest -q -x -m "not slow"`; otherwise keep the current behavior. Check by editing a `.py` file: the hook passes.
- [ ] **Step 8:** `CLAUDE.md`: decisions from the spec and from the "Decisions made by this plan" table, points of attention, commands (`uv run pytest`, `uv run pytest -m slow`, `uv run ruff check`). CI: matrix `macos-latest` / `windows-latest` × Python 3.11 / 3.12, `astral-sh/setup-uv`, `FedericoCarboni/setup-ffmpeg`, then `uv run ruff check` and `uv run pytest`.
- [ ] **Step 9:** commit `chore: socle du projet, CLI minimale, CI`.

---

### Task 2: timecodes and names

**Files:** Create `src/podcleaner_clips/naming.py`, `tests/test_naming.py`

**Interfaces:**
- Produces:
  - `parse_tc(text: str) -> float`: accepts `H:MM:SS`, `HH:MM:SS` and `MM:SS` (1 to 3 minute digits: `45:12` = 2712 s), with `.` or `,` and 1 to 3 decimals; tolerates `;` instead of `:` (`6;25`, `1:17;08`) and `25 min 30` / `25 min`; `ValueError` otherwise.
  - `format_tc(seconds: float) -> str` → `HH:MM:SS.mmm`.
  - `strip_accents(text: str) -> str`
  - `slugify(text: str, max_len: int = 40) -> str`
  - `fallback_abbreviation(title: str) -> str`
  - `film_folder_name(title: str) -> str`
  - `clip_basename(abbr: str, number: int, line: str) -> str` → without extension (`line` = the noted reference).

- [ ] **Step 1: failing tests**

```python
def test_parse_tc_variants():
    assert parse_tc("00:12:34") == 754.0
    assert parse_tc("0:12:34.5") == 754.5
    assert parse_tc("00:12:34,250") == 754.25
    assert parse_tc("45:12") == 2712.0   # MM:SS under an hour
    with pytest.raises(ValueError): parse_tc("45:60")

def test_format_tc():
    assert format_tc(754.25) == "00:12:34.250"

def test_slugify_spec_examples():
    assert slugify("Il s'appelle Juste Leblanc") == "il-s-appelle-juste-leblanc"
    assert slugify("Il a une bonne tête de vainqueur") == "il-a-une-bonne-tete-de-vainqueur"
    assert slugify("Ça, c'est l'été !") == "ca-c-est-l-ete"
    assert slugify("Œuf : « oui » / non ?") == "oeuf-oui-non"
    assert slugify("!!!") == "extrait"

def test_slugify_cuts_on_word_boundary():
    s = slugify("un deux trois quatre cinq six sept huit neuf dix onze")
    assert len(s) <= 40 and not s.endswith("-") and s.split("-")[-1] in "un deux trois quatre cinq six sept huit neuf dix onze".split()

def test_fallback_abbreviation():
    assert fallback_abbreviation("Le Dîner de cons") == "DDC"
    assert fallback_abbreviation("L'Auberge espagnole") == "AE"
    assert fallback_abbreviation("Alien") == "AL"   # single word: first two letters

def test_film_folder_name_is_windows_safe():
    assert film_folder_name("Le Dîner de cons") == "Le Diner de cons"
    assert film_folder_name('Mission: Impossible?') == "Mission Impossible"

def test_clip_basename():
    assert clip_basename("DDC", 1, "Il s'appelle Juste Leblanc") == "DDC-01-il-s-appelle-juste-leblanc"
```

- [ ] **Step 2:** run → FAIL. **Step 3:** implement (`unicodedata.normalize("NFKD")` + a table for `œ/æ`). **Step 4:** run → PASS.
- [ ] **Step 5:** commit `feat: timecodes, slugs et abréviation de repli`.

---

### Task 3: notes file

**Files:** Create `src/podcleaner_clips/notes.py`, `tests/test_notes.py`

**Interfaces:**
- Consumes: `parse_tc` (task 2).
- Produces:
  - `@dataclass(frozen=True) class ClipNote: number: int; start: float; end: float; reference: str; fragments: list[str]; source_line: int` (`reference` = text as noted; `fragments` = pieces to search for; `source_line` = line number, for messages).
  - `@dataclass(frozen=True) class Notes: title: str | None; film_file: str | None; abbreviation: str | None; clips: list[ClipNote]; errors: list[str]`
  - `read_notes(path: Path) -> Notes`
  - `split_fragments(reference: str) -> list[str]`
  - `write_abbreviation(path: Path, abbr: str) -> None`

Rules:
- A clip line **starts and ends with a timecode**: `TC reference TC`. `TC` = anything `parse_tc` accepts; a `:` or `-` right after the first timecode (`25 min 30 : …`) is removed from the reference. The former form `- TC > TC | reference` (bullet `-` or `*`) is still accepted.
- The first timecode is found by trying `parse_tc` on the longest plausible prefix (up to 3 tokens: `25 min 30`), the last one on the longest plausible suffix; the reference is what remains in between, trimmed. Empty reference → error for that line.
- Every other line is ignored. `# Title`, `fichier:` and `abreviation:` (also accept `abréviation:`) are optional and read anywhere before the first clip line.
- Start ≥ end → message in `errors` (`Ligne 7 : le début 00:12:51 n'est pas avant la fin 00:12:34`), clip not kept, numbering of the others unchanged.
- `split_fragments`: splits on `…`, `...` and ` - ` (a dash surrounded by spaces, not the one in `peut-être`), trims, keeps order; a single piece returns `[reference]`.

- [ ] **Step 1: failing tests** (fixture: notes in the real format, neutral content)

```python
REAL = """\
2:35 d'une soirée incroyable 2:51
6;25 si tu n'es pas d'accord tu es quoi ? 6:40
25 min 30 : ça va te remettre les idées en place 25:40
43:00 si je veux … il va comprendre ce soir 44:08
1:16:55 l'histoire se répète - encore une fois 1:17;08
Notes libres : la scène du taxi est trop longue.
"""

def test_reads_real_world_lines(tmp_path):
    n = read_notes(write(tmp_path, REAL))
    assert n.title is None and n.film_file is None
    assert [(c.number, c.start, c.end) for c in n.clips] == [
        (1, 155.0, 171.0), (2, 385.0, 400.0), (3, 1530.0, 1540.0), (4, 2580.0, 2648.0), (5, 4615.0, 4628.0)]
    assert n.clips[2].reference == "ça va te remettre les idées en place"   # ":" removed
    assert n.clips[3].fragments == ["si je veux", "il va comprendre ce soir"]
    assert n.clips[4].fragments == ["l'histoire se répète", "encore une fois"]

def test_reads_legacy_format_with_header(tmp_path): ...  # "Dîner de cons" example with # title, fichier:, abreviation: and "- TC > TC | line" lines
def test_split_fragments_keeps_hyphenated_words(): ...    # "peut-être pas" → ["peut-être pas"]; "a ... b" → ["a", "b"]
def test_ignores_lines_without_both_timecodes(tmp_path): ...  # "2:35 sans fin", "rien 2:51", "Notes libres : …" ignored
def test_bom_and_crlf(tmp_path): ...                      # "﻿2:35 a b 2:51\r\n" → 1 clip
def test_start_after_end_is_reported_not_fatal(tmp_path): ...  # 2 lines, the 1st inverted → clips == [number 2], errors mention "Ligne"
def test_empty_reference_is_an_error(tmp_path): ...       # "2:35 2:51" → error for the line
def test_write_abbreviation_inserts_header_and_keeps_rest(tmp_path):
    # no abreviation line → added after "fichier:" or "# title", otherwise as the first line;
    # rest of the file byte-for-byte identical; CRLF line endings kept; value replaced if the line exists
```

- [ ] **Step 2:** run → FAIL. **Step 3:** implement (read with `encoding="utf-8-sig"`, `newline=""` to keep line endings on write). **Step 4:** run → PASS.
- [ ] **Step 5:** commit `feat: lecture du fichier de notes`.

---

### Task 4: per-person configuration

**Files:** Create `src/podcleaner_clips/config.py`, `tests/test_config.py`; Modify `cli.py` (`config init`, `config show` commands)

**Interfaces:**
- Produces: `@dataclass(frozen=True) class Settings`; `default_config_path() -> Path`; `load_settings(path: Path | None = None) -> Settings`; `write_template(path: Path) -> None`.

| TOML key | Field | Default |
| --- | --- | --- |
| `dossier_episodes` | `episodes_dir: Path` | required |
| `dossier_films` | `films_dir: Path \| None` | none |
| `son_transition` | `transition_sound: Path \| None` | none (required unless `--no-transition`) |
| `doublage_prefere` | `preferred_dub: str` | `"VFF"` (or `"VFQ"`) |
| `[ajustement] tolerance_s` | `tolerance_s` | 15.0 (allowed gap between a noted timecode and the chosen bound; transcribed margin on each side) |
| `[ajustement] sous_titres` | `use_subtitles` | true |
| `[ajustement] score_trouve` / `score_sur` | `score_found`, `score_sure` | 70 / 85 |
| `[ajustement] pause_phrase_s` | `sentence_gap_s` | 0.6 |
| `[ajustement] marge_avant_s` / `marge_apres_s` | `pad_before_s`, `pad_after_s` | 0.10 / 0.25 |
| `[ajustement] modele_whisper` | `whisper_model` | `large-v3-turbo` |
| `[son] fondu_s` | `fade_s` | 0.7 |
| `[son] lufs` / `true_peak` | `lufs`, `true_peak` | -16.0 / -1.0 |
| `[claude] actif` / `modele` | `claude_enabled`, `claude_model` | true / `claude-haiku-5-5` |

Path resolution: argument > `PODCLEANER_CLIPS_CONFIG` > `default_config_path()`. `~` expanded. Missing file → `ClipsError` that gives the expected path and the `podcleaner-clips config init` command.

- [ ] **Step 1: failing tests**: `test_defaults_applied`, `test_env_var_overrides_default_path` (monkeypatch), `test_missing_file_message_mentions_config_init`, `test_unknown_key_is_an_error` (typo → `ClipsError` naming the key), `test_preferred_dub_must_be_vff_or_vfq`, `test_paths_with_accents_and_tilde`, `test_template_roundtrips` (`write_template` then `load_settings` after filling in `dossier_episodes`).
- [ ] **Step 2:** FAIL. **Step 3:** implement with `tomllib`. Template file commented in English. **Step 4:** PASS.
- [ ] **Step 5:** commit `feat: configuration par personne`.

---

### Task 5: film analysis, track choice, subtitles

**Files:** Create `src/podcleaner_clips/media.py`, `scripts/make_test_film.py`, `tests/conftest.py`, `tests/test_media.py`

**Interfaces:**
- Produces:
  - `require_ffmpeg() -> None`: `ClipsError("ffmpeg est introuvable. Installez-le (macOS : brew install ffmpeg ; Windows : winget install ffmpeg) puis relancez.")` if `ffmpeg` or `ffprobe` is missing.
  - `@dataclass(frozen=True) class AudioTrack: index: int` (rank among audio tracks, for `-map 0:a:N`) `; language: str | None; title: str | None; channels: int`
  - `@dataclass(frozen=True) class SubtitleTrack: index: int` (rank among subtitle tracks, for `-map 0:s:N`) `; language: str | None; title: str | None; codec: str`
  - `@dataclass(frozen=True) class VideoInfo: width: int; height: int; fps: str` (ffprobe fraction, e.g. `24000/1001`) `; sar: str`
  - `@dataclass(frozen=True) class MediaInfo: duration: float; audio: list[AudioTrack]; subtitles: list[SubtitleTrack]; video: VideoInfo | None` (first video stream that is not an `attached_pic`)
  - `probe(path: Path) -> MediaInfo`
  - `choose_audio_track(tracks: list[AudioTrack], forced: int | None, preferred_dub: str = "VFF") -> tuple[AudioTrack, str | None]`: the track and a warning in French, or `None`.
  - `choose_subtitle_track(tracks: list[SubtitleTrack]) -> SubtitleTrack | None`
  - `extract_subtitles(path: Path, track: SubtitleTrack) -> str`: SRT text via `ffmpeg -map 0:s:N -f srt -`.
  - `decode_window(path: Path, track: int, start: float, duration: float) -> np.ndarray`: mono 16 kHz float32 via `ffmpeg -ss … -t … -map 0:a:N -ac 1 -ar 16000 -f f32le -`.
  - `scripts/make_test_film.py`: `make_test_film(out: Path, duration: float = 12.0, *, vf_channels: int = 2, video: str = "h264", subtitles: str | None = None) -> Path` (`video`: `"h264"` or `"hevc10_anamorphic"`, the latter added in task 9; `subtitles`: SRT content added as a `fre` "Complets" track); .mkv with a test pattern, track 0 VFF (`fre`, 660 Hz sine, title "Français VFF"), track 1 original (`eng`, 440 Hz sine), track 2 VFQ (`fre`, 880 Hz sine, title "Français VFQ"), `mjpeg` cover as `attached_pic`. Runnable as a script: `python scripts/make_test_film.py out.mkv`.

`choose_audio_track` rules: `forced` out of range → `ClipsError` listing the tracks; otherwise, among French tracks (language `fre`/`fra`/`fr`/`fr-CA`, or title containing `VF`, `Français`, `French`), the first matching `preferred_dub` (see "Dub" in the decisions), otherwise the first French one; no French track → the first one, with the warning `Aucune piste marquée française : piste 0 prise. Pistes : 0 eng « … » 6 canaux, 1 ? … Choisissez avec --audio-track N.`

- [ ] **Step 1: failing tests**

```python
def test_prefers_vff_when_vff_and_vfq_exist(): ...  # [fre "Français VFF", eng, fre "Français VFQ"] → index 0; preferred_dub="VFQ" → index 2
def test_detects_vfq_from_language_tag(): ...       # [fre "Français", fr-CA ""] + "VFQ" → index 1
def test_prefers_french_by_title_when_untagged(): ... # [None "English", None "VFF 5.1"] → index 1
def test_falls_back_to_first_with_warning(): ...    # [None, None] → index 0, warning contains "--audio-track"
def test_forced_out_of_range_lists_tracks(): ...
def test_chooses_full_french_text_subtitles(): ...  # [fre "Forcés" subrip, fre "Complets" subrip, eng subrip, fre "" hdmv_pgs_subtitle] → the "Complets" track
def test_no_usable_subtitles(): ...                 # only image or English subtitles → None
def test_probe_test_film(test_film):                # conftest fixture
    info = probe(test_film)
    assert abs(info.duration - 12.0) < 0.1 and [t.language for t in info.audio] == ["fre", "eng", "fre"]
    assert info.video is not None and info.video.width == 320       # the cover is not taken as the video
def test_extract_subtitles_roundtrip(tmp_path): ... # make_test_film(subtitles=SRT) → extract_subtitles contains the original text
def test_decode_window_length(test_film):
    assert len(decode_window(test_film, 0, 2.0, 3.0)) == pytest.approx(48000, abs=160)
def test_paths_with_spaces_and_accents(tmp_path): ... # film in "Films été/Le Dîner (1998).mkv"
def test_missing_ffmpeg_message(monkeypatch): ...   # shutil.which → None; message contains "brew install ffmpeg"
```

- [ ] **Step 2:** FAIL. **Step 3:** implement (`ffprobe -v error -print_format json -show_format -show_streams`). **Step 4:** PASS.
- [ ] **Step 5:** commit `feat: analyse du film, choix de la VF et des sous-titres`.

---

### Task 5b: locating references in subtitles (pure logic)

**Files:** Create `src/podcleaner_clips/subtitles.py`, `tests/test_subtitles.py`

**Interfaces:**
- Consumes: `Settings` (task 4).
- Produces:
  - `@dataclass(frozen=True) class Cue: start: float; end: float; text: str` (text without `<i>`, `{\an8}` tags, line breaks replaced with spaces).
  - `parse_srt(text: str) -> list[Cue]`: tolerates BOM, CRLF, missing numbers, empty blocks.
  - `normalize(text: str) -> str`: lowercase, no accents, punctuation and apostrophes → space, spaces collapsed. Shared with task 6.
  - `@dataclass(frozen=True) class Anchor: fragment: str; start: float; end: float; score: float`
  - `find_anchors(cues: list[Cue], fragments: list[str], noted_start: float, noted_end: float, s: Settings) -> list[Anchor]`: for each fragment, the best starting subtitle (following subtitles are joined until the fragment's length is reached, for a fragment split across several) within `[noted_start − tolerance_s, noted_end + tolerance_s]`, with `rapidfuzz.fuzz.partial_ratio` on normalized texts; kept if score ≥ `score_found`. On a tie (± 5), the one closest to the middle of the noted range.

- [ ] **Step 1: failing tests**

```python
def test_parse_srt_strips_tags_and_joins_lines(): ...  # "<i>Salut</i>\nça va ?" → "Salut ça va ?"
def test_parse_srt_tolerates_bom_crlf_and_gaps(): ...
def test_anchor_found_despite_approximate_reference(): ...  # subtitle "Ce bébé, c'est une connerie." ; fragment "ce bebe cest une connerie" → score ≥ 85
def test_anchor_limited_to_tolerance_window(): ...     # same text 40 s from the noted range → ignored
def test_anchor_spanning_two_cues(): ...               # fragment split between two consecutive subtitles → found, start of the 1st, end of the 2nd
def test_repeated_line_prefers_closest_to_notes(): ...
def test_short_cue_does_not_match_long_fragment(): ... # "Désolé !" against "un juif a encore crucifié le messie" → no anchor on "Désolé !"
```

- [ ] **Step 2:** FAIL. **Step 3:** implement. **Step 4:** PASS.
- [ ] **Step 5:** commit `feat: repérage des références dans les sous-titres`.

---

### Task 6: snapping bounds (pure logic)

**Files:** Create `src/podcleaner_clips/adjust.py`, `tests/test_adjust.py`

**Interfaces:**
- Consumes: `Settings` (task 4), `normalize`, `Anchor` (task 5b).
- Produces:
  - `@dataclass(frozen=True) class Word: text: str; start: float; end: float` (absolute times in the film).
  - `@dataclass(frozen=True) class Match: fragment: str; first: int; last: int; score: float` (indices in the word list).
  - `find_fragments(words: list[Word], fragments: list[str], anchors: list[Anchor], noted_start: float, noted_end: float, s: Settings) -> list[Match | None]`: one result per fragment, `None` if not found.
  - `sentence_starts(words: list[Word], s: Settings) -> list[int]` and `sentence_ends(words: list[Word], s: Settings) -> list[int]`: indices of the words that start / end a sentence.
  - `@dataclass(frozen=True) class Cut: start: float; end: float; method: str` (`"notes"`, `"whisper"`, `"claude"`) `; score: float | None; doubt: str | None` (reason in French, `None` when confident).
  - `@dataclass(frozen=True) class Decision: cut: Cut; matches: list[Match | None]; first_word: int | None; last_word: int | None`
  - `adjust_cut(words: list[Word], fragments: list[str], anchors: list[Anchor], noted_start: float, noted_end: float, s: Settings) -> Decision` (`words` covers `[noted_start − tolerance_s, noted_end + tolerance_s]`).
  - `cut_from_words(words: list[Word], first: int, last: int, s: Settings) -> Cut`: bounds from two word indices, with paddings; reused by task 7.
  - `bounds_ok(words: list[Word], first: int, last: int, matches: list[Match | None], noted_start: float, noted_end: float, s: Settings) -> bool`: start within `noted_start ± tolerance_s`, end within `noted_end ± tolerance_s`, every found fragment included, `first ≤ last`. Reused by task 7.

Algorithm:
- `find_fragments`: for each fragment, windows of `n−1` to `n+2` words of the transcription (`n` = words in the fragment), at least as long as the fragment in characters, scored with `fuzz.partial_ratio` on normalized texts. If there is an anchor for this fragment, search only within ±5 s of the anchor; otherwise in the whole window. Found if score ≥ `score_found`; among ties (± 5 points), the one closest to the anchor, otherwise to the middle of the noted range.
- `adjust_cut`:
  - No fragment found: `Cut` on the noted timecodes, each moved outward to a word boundary, method `"notes"`, `doubt = "référence introuvable"`.
  - Start: among `sentence_starts` whose word starts within `[noted_start − tolerance_s, noted_start + tolerance_s]` and no later than the first word of the first found fragment, the one closest to `noted_start`. None: start of the word closest to `noted_start` (not past the first fragment), `doubt = "pas de début de phrase près du timecode noté"`.
  - End is symmetrical with `sentence_ends`, `noted_end` and the last word of the last found fragment.
  - Paddings: `cut_from_words` applies `− pad_before_s` / `+ pad_after_s` without entering the neighbouring word.
  - A fragment not found while others are, or a score < `score_sure`: `doubt` says so ("fragment introuvable : …", "référence peu sûre : …"). Method `"whisper"`.

- [ ] **Step 1: failing tests** (hand-written `Word` lists, a scene of about 60 s)

```python
def test_scene_kept_with_short_reference(): ...
    # notes 27:15 > 27:37, reference "ce bébé c'est une connerie" around 27:20 → the clip keeps ~22 s,
    # start = sentence start closest to 27:15, end = sentence end closest to 27:37
def test_notes_10s_late_still_snap_to_sentences(): ...   # real sentences 10 s before the notes → bounds on those sentences, fragment included
def test_two_fragments_both_included(): ...              # "si je veux … il va comprendre ce soir" over 68 s → both in the clip
def test_end_extended_to_include_late_fragment(): ...    # fragment ending 4 s after noted_end → end after it
def test_misspelled_reference_found(): ...               # "tu as été plus solide qu'un rock" vs transcription "plus solide qu'un roc" → found
def test_anchor_restricts_search(): ...                  # fragment present twice; the anchor points to the 2nd → match on the 2nd
def test_never_cuts_a_word(): ...                        # bounds always on word starts / ends, paddings without overlapping neighbours
def test_unfound_reference_keeps_notes_on_word_bounds(): ... # → method "notes", doubt "référence introuvable"
def test_partially_found_reference_is_flagged(): ...     # 1 of 2 fragments found → method "whisper", doubt names the missing fragment
def test_bounds_ok_rejects_cut_missing_a_fragment(): ...
```

- [ ] **Step 2:** FAIL. **Step 3:** implement. **Step 4:** PASS.
- [ ] **Step 5:** commit `feat: calage des bornes sur la scène notée`.

---

### Task 7: transcription and Claude's opinion

**Files:** Create `src/podcleaner_clips/transcribe.py`, `src/podcleaner_clips/claude.py`, `tests/test_transcribe.py`, `tests/test_claude.py`

Load the `claude-api` skill before writing `claude.py`.

**Interfaces:**
- Consumes: `decode_window` (task 5), `Word`, `Decision`, `cut_from_words`, `bounds_ok` (task 6), `fallback_abbreviation` (task 2), `Settings`.
- Produces:
  - `class Transcriber(Protocol): def words(self, audio: np.ndarray, offset: float) -> list[Word]`
  - `make_transcriber(model: str) -> Transcriber`: mlx-whisper on macOS arm64, faster-whisper (`compute_type="int8"`) elsewhere; `language="fr"`, `word_timestamps=True`; model loaded once per run, on first call. `offset` is added to the times to get absolute times.
  - `@dataclass(frozen=True) class ClaudeAdvice: kind: str; answer: str; reason: str; model: str` (written as is to the index).
  - `class ClaudeClient`: `available: bool` (key present and `claude_enabled`); `propose_abbreviation(title: str, film_file: str | None) -> tuple[str, ClaudeAdvice | None]`; `choose_bounds(words: list[Word], reference: str, decision: Decision, noted_start: float, noted_end: float, s: Settings) -> tuple[Cut, ClaudeAdvice | None]`.

Rules:
- Abbreviation: expected answer `^[A-Z0-9]{2,6}$`; unavailable, network error or invalid answer → `fallback_abbreviation(title)` and `None`.
- Bounds: called for **every** clip when Claude is available and adjustment is on. Send the numbered words with their times, the reference as noted, the noted timecodes (stating they are approximate, ±15 s, and that the clip must keep the noted scene), the found fragments and the heuristic proposal. Structured answer (tool use) `{premier_mot: int, dernier_mot: int, raison: str}`; accepted only if `bounds_ok`, then converted by `cut_from_words` with `method="claude"`; otherwise `decision`'s cut. Unavailable → `decision`'s cut, `doubt` kept.
- An API error never stops the run: a warning, then the fallback.

- [ ] **Step 1: failing tests** (`test_claude.py` with an injected fake Anthropic client, no network)

```python
def test_abbreviation_without_key_uses_initials(monkeypatch): ...  # no ANTHROPIC_API_KEY → ("DDC", None)
def test_abbreviation_invalid_answer_falls_back(): ...           # fake client answers "Le dîner" → "DDC"
def test_abbreviation_valid_answer(): ...                         # "DDC" → ("DDC", advice.kind == "abreviation")
def test_choose_bounds_applies_claude_choice(): ...               # valid indices → Cut.method == "claude"
def test_choose_bounds_rejects_out_of_bounds(): ...               # index 999 → original cut
def test_choose_bounds_rejects_cut_missing_a_fragment(): ...      # bounds that leave out a found fragment → original cut
def test_api_error_falls_back_with_warning(): ...                 # fake client raises anthropic.APIError
```

And `test_transcribe.py` (marked `slow`, skipped without `say` on macOS): generate `say -v Thomas "Bonjour. Il s'appelle Juste Leblanc."`, transcribe, check that `find_fragments(words, ["juste leblanc"], [], 0, 5, s)[0].score >= 85` and that times are increasing.
- [ ] **Step 2:** FAIL. **Step 3:** implement. **Step 4:** `uv run pytest` then `uv run pytest -m slow tests/test_transcribe.py` → PASS.
- [ ] **Step 5:** commit `feat: transcription par fenêtre et avis de Claude`.

---

### Task 8: audio rendering

**Files:** Create `src/podcleaner_clips/render_audio.py`, `tests/test_render_audio.py`

**Interfaces:**
- Consumes: `Settings`, `AudioTrack`.
- Produces:
  - `@dataclass(frozen=True) class ClipLayout: film_start: float; film_end: float; fade_s: float; transition_s: float | None` with properties `clip_s`, `film_offset` (`max(0, transition_s − fade_s)`, 0 without transition), `outro_offset` (`film_offset + clip_s − fade_s`), `total_s` (`max(film_offset + clip_s, outro_offset + transition_s)`, or `clip_s`).
  - `audio_filter(layout: ClipLayout, with_transition: bool) -> str`: `-filter_complex` string.
  - `render_audio(film: Path, track: AudioTrack, layout: ClipLayout, transition: Path | None, out_wav: Path, s: Settings) -> None`
  - `measure_loudness(path: Path) -> tuple[float, float]` (integrated LUFS, true peak dBTP) via `ebur128=peak=true`.

Chain: film `-ss film_start -t clip_s -map 0:a:N`, `aresample=48000`, `aformat=channel_layouts=stereo` (ffmpeg downmix), `afade=in:d=fade_s`, `afade=out:st=clip_s−fade_s:d=fade_s`, `adelay=film_offset`; transition played twice (`asplit`), at 0 and at `outro_offset`; `amix=normalize=0`; `apad` + `atrim` to `total_s`. Then two-pass `loudnorm` normalization (measure as JSON, then `linear=true` with the measured values, `I=lufs:TP=true_peak:LRA=11`), output `-ar 48000 -c:a pcm_s24le`. Write to a temporary file in the same folder first, then rename, so a half-written WAV is never left behind.

- [ ] **Step 1: failing tests**

```python
def test_layout_with_transition():
    l = ClipLayout(100.0, 110.0, fade_s=0.7, transition_s=2.0)
    assert (l.film_offset, l.outro_offset, l.total_s) == pytest.approx((1.3, 10.6, 12.6))
def test_layout_without_transition():
    assert ClipLayout(100.0, 110.0, 0.7, None).total_s == pytest.approx(10.0)
def test_layout_transition_shorter_than_fade(): ...   # transition 0.4 → film_offset 0, total ≥ clip_s
def test_render_duration_and_loudness(test_film, transition_wav, tmp_path):
    render_audio(..., ClipLayout(2.0, 8.0, 0.7, 1.5), ...)
    # ffprobe duration ≈ 7.6 s ± 0.05; 48000 Hz; 2 channels; LUFS ∈ [-17, -15]; true peak ≤ -0.9
def test_render_no_transition_fades_edges(...): ...  # first 50 ms much quieter than the middle (≥ 20 dB difference)
def test_vf_51_is_downmixed_to_stereo(tmp_path): ... # make_test_film(vf_channels=6) → 2-channel output, LUFS ∈ [-17, -15]
```

- [ ] **Step 2:** FAIL. **Step 3:** implement. **Step 4:** PASS.
- [ ] **Step 5:** commit `feat: rendu audio avec fondus, transition et normalisation`.

---

### Task 9: video rendering

**Files:** Create `src/podcleaner_clips/render_video.py`, `tests/test_render_video.py`

**Interfaces:**
- Consumes: `ClipLayout`, `VideoInfo`, the WAV from task 8.
- Produces: `render_video(film: Path, video: VideoInfo, layout: ClipLayout, audio_wav: Path, out_mp4: Path) -> None`.

Chain: `color=black` (film size and frame rate) for `film_offset`, film picture `-ss film_start -t clip_s`, black for `total_s − film_offset − clip_s`; each segment goes through `scale=W:H,setsar=1,fps=<fps>,format=yuv420p` before `concat=n=3:v=1:a=0` (W×H = display size, SAR applied); zero-length segments omitted. Sound: the WAV from task 8 as AAC 192 kb/s. `libx264 -crf 18 -preset medium -movflags +faststart`. Written to a temporary file, then renamed.

- [ ] **Step 1: failing tests**

```python
def test_video_matches_audio_duration(test_film, transition_wav, tmp_path): ...
    # MP4 video and audio duration = layout.total_s ± 0.1; codecs h264 / aac; pix_fmt yuv420p
def test_black_during_intro(...): ...        # frame at t=0.2 s: mean luma (signalstats YAVG) < 20; at film_offset + 1 s: > 20
def test_anamorphic_hevc_10bit_23976(tmp_path): ... # make_test_film(video="hevc10_anamorphic") → renders without error, yuv420p, SAR 1:1
def test_no_transition_has_no_black(...): ... # transition_s=None → no black frame at the start
```

- [ ] **Step 2:** FAIL (add `video="hevc10_anamorphic"` to `make_test_film`: `libx265 -pix_fmt yuv420p10le`, `setsar=4/3`, 24000/1001). **Step 3:** implement. **Step 4:** PASS.
- [ ] **Step 5:** commit `feat: rendu vidéo avec écran noir pendant la transition`.

---

### Task 10: index and incremental rerun

**Files:** Create `src/podcleaner_clips/index.py`, `tests/test_index.py`

**Interfaces:**
- Consumes: `ClipNote`, `Cut`, `ClaudeAdvice`, `AudioTrack`.
- Produces:
  - `fingerprint(note: ClipNote, *, adjust: bool, transition: bool, track: int, transition_sha: str | None, render: dict) -> str`: sha256 of a sorted JSON; the clip number is not part of it.
  - `file_sha256(path: Path) -> str`
  - `@dataclass class ClipEntry` (one entry of `extraits[]`) and `@dataclass class FilmIndex`; `load_index(path: Path) -> FilmIndex | None`; `save_index(index: FilmIndex, path: Path) -> None` (atomic write, `ensure_ascii=False`, indent 2).
  - `@dataclass(frozen=True) class Action: number: int; kind: str` (`"nouveau"`, `"modifie"`, `"inchange"`, `"renomme"`, `"manquant"`) `; reuse: ClipEntry | None; rename_from: dict[str, Path]`
  - `plan_actions(notes: list[ClipNote], fingerprints: dict[int, str], previous: FilmIndex | None, out_dir: Path, wanted: set[str]) -> tuple[list[Action], list[Path]]`: `wanted` ⊂ `{"audio", "video"}`; the second element lists orphan files.

`extraits.json` schema:

```json
{
  "version": 1,
  "film": {"titre": "...", "abreviation": "DDC", "fichier": "...", "piste_audio": {"index": 1, "langue": "fre", "titre": "VF"}},
  "avis_claude": [{"type": "abreviation", "reponse": "DDC", "raison": "...", "modele": "claude-haiku-5-5"}],
  "extraits": [{
    "numero": 1, "reference": "...", "fragments_trouves": ["..."], "empreinte": "…",
    "notes": {"debut": "00:12:34.000", "fin": "00:12:51.000"},
    "retenu": {"debut": "00:12:33.420", "fin": "00:12:51.880", "methode": "whisper", "score": 96.2, "doute": null},
    "avis_claude": null,
    "duree_s": 21.06,
    "fichiers": {"audio": "audio/DDC-01-il-s-appelle-juste-leblanc.wav", "video": "video/DDC-01-il-s-appelle-juste-leblanc.mp4"}
  }]
}
```

Paths relative to the film folder, always with `/`. `inchange` = same fingerprint and all wanted files present: the chosen cut is reused as is, without Whisper or Claude (reproducibility). Same fingerprint under another number → `renomme`. Same fingerprint but a wanted file missing → `manquant` (only that file is rendered, with the chosen cut).

- [ ] **Step 1: failing tests**

```python
def test_first_run_all_new(): ...
def test_unchanged_when_same_fingerprint_and_files_exist(tmp_path): ...
def test_changed_line_only_that_clip(): ...
def test_transition_sha_change_invalidates_all(): ...
def test_deleted_output_file_is_missing_kind(tmp_path): ...
def test_inserted_line_renames_shifted_clips(tmp_path): ... # new line at 1 → old 01 becomes "renomme" to 02
def test_removed_line_reported_as_orphan(tmp_path): ...
def test_index_roundtrip_utf8(tmp_path): ...              # accented reference read back identically, file readable as UTF-8
```

- [ ] **Step 2:** FAIL. **Step 3:** implement. **Step 4:** PASS.
- [ ] **Step 5:** commit `feat: index extraits.json et relance incrémentale`.

---

### Task 11: pipeline and `run` command

**Files:** Create `src/podcleaner_clips/pipeline.py`, `tests/test_pipeline.py`; Modify `cli.py`

**Interfaces:**
- Consumes: everything above.
- Produces:
  - `@dataclass(frozen=True) class RunOptions: notes: Path; film: Path | None = None; transition: bool = True; audio: bool = True; video: bool = True; adjust: bool = True; dry_run: bool = False; audio_track: int | None = None; config: Path | None = None`
  - `run(opts: RunOptions, *, transcriber: Transcriber | None = None, claude: ClaudeClient | None = None, echo: Callable[[str], None] = typer.echo) -> FilmIndex | None` (injections for tests).
  - CLI: `podcleaner-clips run NOTES [--film PATH] [--no-transition] [--audio-only | --video-only] [--no-adjust] [--dry-run] [--audio-track N] [--config PATH]`.

Flow: `require_ffmpeg` → `load_settings` → `read_notes` (line errors shown) → film: `--film`, otherwise `fichier:` (absolute, otherwise relative to the notes folder, otherwise to `dossier_films`); none → `ClipsError` listing the places searched and mentioning `--film` → title: the notes' `# `, otherwise derived from the film's name (see "Film title") → `probe` + `choose_audio_track(…, preferred_dub)` → if `use_subtitles` and `choose_subtitle_track` finds a track: `extract_subtitles` once, `parse_srt` → abbreviation (from the notes, otherwise Claude/fallback then `write_abbreviation` unless `--dry-run`) → `plan_actions` → for each clip to do: `find_anchors`, window `[start − tolerance_s, end + tolerance_s]` clamped to `[0, duration]`, `transcriber.words`, `adjust_cut`, then `choose_bounds` if Claude is available; then renders; renames → `save_index` → summary.

Rules:
- `--audio-only` and `--video-only` together → `ClipsError`. `--video-only` still renders the WAV into a temporary file, deleted afterwards.
- `--no-adjust`: no subtitles, Whisper or Claude for cuts, method `"notes"`.
- A clip whose end is past the film's duration → error for that clip, the others go on; exit code 1 if at least one clip failed, 0 otherwise.
- No transition sound configured without `--no-transition` → `ClipsError` mentioning `son_transition` and `--no-transition`.
- `--dry-run`: transcription and snapping are done, nothing is written (no file, no folder, no abbreviation in the notes, no index).
- Summary: one line per clip `01  DDC-01-il-s-appelle-juste-leblanc  00:12:34.000 > 00:12:51.000  →  00:12:33.420 > 00:12:51.880  21,1 s  nouveau`, followed by `⚠ <doubt>` when needed; then warnings (track, orphans) and the folder path.

- [ ] **Step 1: failing tests** (test film, fake `Transcriber` returning fixed words, unavailable `ClaudeClient`)

```python
def test_end_to_end_no_adjust(tmp_path, test_film, transition_wav): ...
    # 2 clips → audio/XX-01-….wav, audio/XX-02-….wav, video/….mp4, extraits.json; abbreviation written into the notes
def test_dry_run_writes_nothing(tmp_path, ...): ...         # no new file or folder; notes unchanged; names displayed
def test_audio_only_and_video_only(...): ...
def test_audio_and_video_only_together_is_error(...): ...
def test_second_run_is_all_unchanged(...): ...              # no render ffmpeg launched (counted via monkeypatch), summary "inchangé"
def test_clip_past_film_end_fails_alone(...): ...           # code 1, the other clip rendered
def test_film_resolved_from_films_dir(...): ...
def test_film_option_and_title_from_film_name(...): ...  # notes without header + --film "X (2015) Bluray.mkv" → folder "X (2015)"
def test_subtitles_used_when_present(...): ...          # test film with French subtitles → anchors passed to adjust_cut (spy)
def test_fake_transcriber_cut_written_to_index(...): ...    # method "whisper", chosen timecodes ≠ noted
```

- [ ] **Step 2:** FAIL. **Step 3:** implement. **Step 4:** PASS.
- [ ] **Step 5:** manual test on a real film (`samples/` folder, outside the repo): `uv run podcleaner-clips run samples/notes.md --dry-run`, then without `--dry-run`; listen to two clips.
- [ ] **Step 6:** commit `feat: commande run de bout en bout`.

---

### Task 12: project skills, README and Windows check

**Files:** Create `.claude/skills/test-rapide/SKILL.md`, `.claude/skills/compat-windows/SKILL.md`, `scripts/check_windows_compat.py`, `tests/test_check_windows_compat.py`; Modify `README.md`, `README.fr.md`

**Interfaces:**
- Consumes: `scripts/make_test_film.py`, the CLI.
- Produces: `check(root: Path) -> list[str]` in `scripts/check_windows_compat.py` (one line per problem: `file:line : message`), exit code 1 if the list is not empty.

- [ ] **Step 1: failing test**: `check` flags, in a test folder, `open(p)` and `p.read_text()` without `encoding=`, a hard-coded path (`"/Users/"`, `"C:\\"`), `subprocess` with `shell=True`; and flags nothing in the project's `src/`.
- [ ] **Step 2:** FAIL. **Step 3:** implement (`ast` module). **Step 4:** PASS.
- [ ] **Step 5:** **test-rapide** skill (written with `skill-creator`): generate a 20 s film with `make_test_film.py` (VF + original), a notes file with two clips in the real format (`TC reference TC`), a temporary config, run `run --no-adjust` then `run`, and check names, durations (`ffprobe`), levels (-16 ± 1 LUFS, ≤ -1 dBTP) and the VF track (660 Hz sine dominant). **compat-windows** skill: run `check_windows_compat.py`, `require_ffmpeg`, then a `run --no-adjust` in a folder named `Été à l'écran/`; to do before each release.
- [ ] **Step 6:** README in English and French (`README.md`, `README.fr.md`): installation (uv, ffmpeg on macOS and Windows), `config init`, notes file format, options, outputs, optional Claude.
- [ ] **Step 7:** `uv run ruff check && uv run pytest`, then run the test-rapide skill → everything passes.
- [ ] **Step 8:** commit `docs: skills test rapide et compatibilité Windows, README`.

---

## Order and parallelism

1 → 2 → 3 → 4 → 5, then 5b (depends only on 4) and 8 (depends on 5) can proceed in parallel; 6 after 5b; 7 after 5 and 6; 9 after 8; 10 after 3, 6 and 7; 11 after everything; 12 last.

## Test data

- Generated by `scripts/make_test_film.py` for automated tests (no film in the repository).
- A real film and a real notes file in `samples/` (ignored by git) for task 11's manual test. Already available: `samples/the-night-before.md`, 16 clips noted by the maintainer on *The Night Before* (2015), a film with 5.1 VFF and VFQ, original audio, French text subtitles and an `mjpeg` cover (film path at the top of the file).
