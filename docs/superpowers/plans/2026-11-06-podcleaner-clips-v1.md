# Podcleaner-clips v1: implementation plan

[Français](2026-11-06-podcleaner-clips-v1.fr.md) · **English** — translated from the French original. User-facing strings (messages, config keys, index keys, test data) stay in French, because the tool's interface is French.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** a `podcleaner-clips run notes.md` CLI that reads a film's notes file, snaps each clip to its line with Whisper, then writes the audio (WAV) and video (MP4) clips with fades, transition sound and normalization, plus the `extraits.json` index.

**Architecture:** Python package `src/podcleaner_clips/`. ffmpeg/ffprobe, Whisper and Claude stay at the edges, behind narrow functions; everything that decides (reading notes, track choice, cut snapping, clip time layout, fingerprints) is made of pure functions testable without media. A clip is rendered once as a normalized WAV; the MP4 reuses that WAV as its soundtrack.

**Tech Stack:** Python 3.11–3.12, uv, Typer, platformdirs, rapidfuzz, numpy, mlx-whisper (macOS arm64) / faster-whisper (elsewhere), anthropic, ffmpeg/ffprobe (PATH), pytest, Ruff.

**Spec:** `docs/spec.fr.md` (original) · `docs/spec.md` (English translation). Sibling project for conventions: `../podcleaner-editor/docs/superpowers/plans/2026-11-05-m1-fondations-analyse.md`.

## Global Constraints

- Runs on macOS and Windows; paths via `pathlib`, no hard-coded path, text files read and written with `encoding="utf-8"`.
- No account or API key required: without `ANTHROPIC_API_KEY`, every Claude call has a fallback (title initials, widest cut).
- Inputs: `.mkv`, `.avi`, `.mp4`.
- Always the VF (French dub) audio track; if no track is tagged French, the first one, with a warning.
- Adjustment: up to 4 s on each side of the noted timecodes, never in the middle of a word; better some margin than a cut-off line.
- A full film is never transcribed: only a window around each clip.
- Fades: 0.7 s at the start and the end.
- Audio: 48 kHz WAV, -16 LUFS integrated, -1 dBTP.
- Video: H.264 + AAC MP4, same cut and same sound as the audio; black screen during the transition sound.
- Naming: `{abbreviation}-{2-digit number}-{first-words-of-the-line}.{wav|mp4}`.
- Output: `{dossier_episodes}/{film-name}/audio/`, `…/video/`, `…/extraits.json`.
- A new run only rewrites the clips that were added or changed.
- Out of scope for v1: live player, video transition effects, subtitles.
- Code identifiers in English; displayed messages, config file keys and index keys in French.
- Fast tests (`pytest -m "not slow"`) without a Whisper model or network; they may call ffmpeg. Tests that load Whisper are marked `slow`.
- `main` is protected: each task is done on a branch (`feat/…`, `fix/…`, `docs/…`, `chore/…`) and lands through a pull request. Commits follow Conventional Commits, title in English then French (`type: English / français`); the commit messages given in the tasks below only show the French part, to be completed. PR title and description: English then French (see `CONTRIBUTING.md`).
- Docs in English (`*.md`) and French (`*.fr.md`): any change to one updates the other in the same PR. `CLAUDE.md` is in French.

## Decisions made by this plan (not fixed by the spec)

| Topic | Decision |
| --- | --- |
| Package / command | `podcleaner_clips` / `podcleaner-clips` (`run`, `config init`, `config show`, `version`) |
| Configuration | TOML in `platformdirs.user_config_dir("podcleaner-clips")/config.toml`, overridable with `--config` or `PODCLEANER_CLIPS_CONFIG` |
| Film folder | Title from the notes file's `# ` heading, without accents and without `<>:"/\|?*` (`Le Dîner de cons` → `Le Diner de cons`), to avoid NFC/NFD issues between Mac and Windows |
| Line slug | Lowercase, no accents, apostrophes and punctuation → `-`, whole words up to 40 characters; empty → `extrait` |
| Fallback abbreviation | Drop the leading article (le, la, les, l', un, une, des, the, a, an), uppercase initials of the remaining words, 2 to 6 characters (`Le Dîner de cons` → `DDC`) |
| Number | Order of the line in the notes file, starting at 1 |
| Transition placement | Film sound starts `transition − 0.7 s` after the beginning and fades in over 0.7 s; the closing transition starts when the fade-out starts. Same sound file for intro and outro |
| Picture during the transition | Black as long as the film sound has not started (and after it stops), so the picture stays in sync with the sound |
| Channels | Stereo output; a 5.1 VF is downmixed to stereo by ffmpeg, keeping the center (dialogue) channel |
| WAV bit depth | 24-bit |
| Doubt | rapidfuzz score < 50: line not found, noted timecodes kept. 50–80, or two occurrences within 5 points: doubtful → Claude's opinion if a key is set, otherwise the best occurrence closest to the noted timecodes, flagged |
| Models | Whisper `large-v3-turbo` (mlx: `mlx-community/whisper-large-v3-turbo`), language `fr`; Claude `claude-haiku-5-5`; both configurable |
| Clips removed from the notes | Their files are not deleted, only listed as "orphans" in the summary |

## Review Focus

1. **Real-world notes file**: UTF-8 BOM, Windows line endings, `H:MM:SS` timecodes or timecodes with milliseconds (`00:12:34.5`, `00:12:34,500`), start ≥ end. Valid lines must be read; a line with start ≥ end is an error reported for that clip without stopping the others. Tests in task 3.
2. **5.1 VF** (common in .mkv files): the clip must come out in stereo, dialogue audible, at the right level. Test in task 8.
3. **Accented and punctuated lines**: `Ça, c'est l'été !` → `ca-c-est-l-ete`; no character forbidden on Windows in a file name. Tests in task 2.
4. **Anamorphic video, 23.976 fps, 10-bit HEVC**: the black segments and the film picture must concatenate without ffmpeg errors and come out as yuv420p playable everywhere. Test in task 9.
5. **Rerun after an edit**: changing one line only redoes that clip; changing the transition sound redoes everything; deleting an output file redoes it; inserting a line renames the shifted files instead of recomputing them. Tests in task 10.

---

## Files

```
pyproject.toml, uv.lock, CLAUDE.md
.gitignore, LICENSE, README(.fr).md, CONTRIBUTING(.fr).md, .github/CODEOWNERS   (already present)
.github/workflows/ci.yml
.claude/hooks/python_checks.py           (modified: runs through uv run)
.claude/skills/test-rapide/SKILL.md
.claude/skills/compat-windows/SKILL.md
scripts/make_test_film.py                test film (VF + original), used by tests and the skill
scripts/check_windows_compat.py
src/podcleaner_clips/__init__.py         __version__
src/podcleaner_clips/cli.py              Typer app: version, config, run
src/podcleaner_clips/errors.py           ClipsError (user message, exit code 2)
src/podcleaner_clips/naming.py           timecodes, slug, fallback abbreviation, file names
src/podcleaner_clips/notes.py            reading the notes file, writing the abbreviation
src/podcleaner_clips/config.py           Settings + TOML loading
src/podcleaner_clips/media.py            ffmpeg presence, ffprobe, track choice, window decoding
src/podcleaner_clips/adjust.py           Word, line search, cut snapping (pure)
src/podcleaner_clips/transcribe.py       transcription of a window (mlx / faster-whisper)
src/podcleaner_clips/claude.py           abbreviation and cut choice, with fallbacks
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
  - `parse_tc(text: str) -> float`: accepts `H:MM:SS`, `HH:MM:SS`, with `.` or `,` and 1 to 3 decimals; `ValueError` otherwise.
  - `format_tc(seconds: float) -> str` → `HH:MM:SS.mmm`.
  - `strip_accents(text: str) -> str`
  - `slugify(text: str, max_len: int = 40) -> str`
  - `fallback_abbreviation(title: str) -> str`
  - `film_folder_name(title: str) -> str`
  - `clip_basename(abbr: str, number: int, line: str) -> str` → without extension.

- [ ] **Step 1: failing tests**

```python
def test_parse_tc_variants():
    assert parse_tc("00:12:34") == 754.0
    assert parse_tc("0:12:34.5") == 754.5
    assert parse_tc("00:12:34,250") == 754.25
    with pytest.raises(ValueError): parse_tc("12:34")

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
  - `@dataclass(frozen=True) class ClipNote: number: int; start: float; end: float; line: str; source_line: int` (line number in the file, for messages).
  - `@dataclass(frozen=True) class Notes: title: str; film_file: str | None; abbreviation: str | None; clips: list[ClipNote]; errors: list[str]`
  - `read_notes(path: Path) -> Notes`: `ClipsError` if there is no `# ` title.
  - `write_abbreviation(path: Path, abbr: str) -> None`

Rules: a clip line is `- HH:MM:SS > HH:MM:SS | line` (flexible spaces, `*` accepted as a bullet), anywhere in the file; every other line is ignored. `fichier:` and `abreviation:` (also accept `abréviation:`) are read anywhere before the first clip line. Start ≥ end → message in `errors` (`Ligne 7 : le début 00:12:51 n'est pas avant la fin 00:12:34`), clip not kept, numbering of the others unchanged.

- [ ] **Step 1: failing tests** (the spec's example file as a text fixture)

```python
def test_reads_spec_example(tmp_path):
    n = read_notes(write(tmp_path, SPEC_EXAMPLE))
    assert n.title == "Le Dîner de cons"
    assert n.film_file == "Le Diner de cons (1998).mkv"
    assert n.abbreviation == "DDC"
    assert [(c.number, c.start, c.end) for c in n.clips] == [(1, 754.0, 771.0), (2, 2822.0, 2840.0)]
    assert n.clips[0].line == "Il s'appelle Juste Leblanc"

def test_ignores_free_notes_and_bad_lines(tmp_path): ...       # "La scène du téléphone…", "- 00:12 > x" ignored
def test_bom_and_crlf(tmp_path): ...                             # "\ufeff# Titre\r\n- 00:00:01 > 00:00:02 | a\r\n" → 1 clip, title "Titre"
def test_start_after_end_is_reported_not_fatal(tmp_path): ...   # 2 lines, the 1st inverted → clips == [number 2], errors mention "Ligne"
def test_missing_title_raises(tmp_path): ...
def test_write_abbreviation_inserts_after_fichier_and_keeps_rest(tmp_path):
    # no abreviation line → added right after "fichier:", rest of the file byte-for-byte identical
    # CRLF line endings kept; if the line already exists, its value is replaced
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
| `[ajustement] marge_max_s` | `adjust_max_s` | 4.0 |
| `[ajustement] marge_transcription_s` | `window_margin_s` | 5.0 |
| `[ajustement] score_min` / `score_sur` | `score_min`, `score_sure` | 50 / 80 |
| `[ajustement] pause_phrase_s` | `sentence_gap_s` | 0.6 |
| `[ajustement] marge_avant_s` / `marge_apres_s` | `pad_before_s`, `pad_after_s` | 0.10 / 0.25 |
| `[ajustement] modele_whisper` | `whisper_model` | `large-v3-turbo` |
| `[son] fondu_s` | `fade_s` | 0.7 |
| `[son] lufs` / `true_peak` | `lufs`, `true_peak` | -16.0 / -1.0 |
| `[claude] actif` / `modele` | `claude_enabled`, `claude_model` | true / `claude-haiku-5-5` |

Path resolution: argument > `PODCLEANER_CLIPS_CONFIG` > `default_config_path()`. `~` expanded. Missing file → `ClipsError` that gives the expected path and the `podcleaner-clips config init` command.

- [ ] **Step 1: failing tests**: `test_defaults_applied`, `test_env_var_overrides_default_path` (monkeypatch), `test_missing_file_message_mentions_config_init`, `test_unknown_key_is_an_error` (typo → `ClipsError` naming the key), `test_paths_with_accents_and_tilde`, `test_template_roundtrips` (`write_template` then `load_settings` after filling in `dossier_episodes`).
- [ ] **Step 2:** FAIL. **Step 3:** implement with `tomllib`. Template file commented in French. **Step 4:** PASS.
- [ ] **Step 5:** commit `feat: configuration par personne`.

---

### Task 5: film analysis and track choice

**Files:** Create `src/podcleaner_clips/media.py`, `scripts/make_test_film.py`, `tests/conftest.py`, `tests/test_media.py`

**Interfaces:**
- Produces:
  - `require_ffmpeg() -> None`: `ClipsError("ffmpeg est introuvable. Installez-le (macOS : brew install ffmpeg ; Windows : winget install ffmpeg) puis relancez.")` if `ffmpeg` or `ffprobe` is missing.
  - `@dataclass(frozen=True) class AudioTrack: index: int` (rank among audio tracks, for `-map 0:a:N`) `; language: str | None; title: str | None; channels: int`
  - `@dataclass(frozen=True) class VideoInfo: width: int; height: int; fps: str` (ffprobe fraction, e.g. `24000/1001`) `; sar: str`
  - `@dataclass(frozen=True) class MediaInfo: duration: float; audio: list[AudioTrack]; video: VideoInfo | None` (first video stream that is not an `attached_pic`)
  - `probe(path: Path) -> MediaInfo`
  - `choose_audio_track(tracks: list[AudioTrack], forced: int | None) -> tuple[AudioTrack, str | None]`: returns the track and a warning in French, or `None`.
  - `decode_window(path: Path, track: int, start: float, duration: float) -> np.ndarray`: mono 16 kHz float32 via `ffmpeg -ss … -t … -map 0:a:N -ac 1 -ar 16000 -f f32le -`.
  - `scripts/make_test_film.py`: `make_test_film(out: Path, duration: float = 12.0, *, vf_channels: int = 2, video: str = "h264") -> Path` (`video`: `"h264"` or `"hevc10_anamorphic"`, the latter added in task 9); .mkv with a test pattern, track 0 original (`eng`, 440 Hz sine), track 1 VF (`fre`, 660 Hz sine, title "VF"). Runnable as a script: `python scripts/make_test_film.py out.mkv`.

`choose_audio_track` rules: `forced` out of range → `ClipsError` listing the tracks; otherwise the first track whose language is `fre`/`fra`/`fr` or whose title contains `VF`, `VFF`, `VFQ`, `French` or `Français` (case-insensitive); otherwise the first one, with the warning `Aucune piste marquée française : piste 0 prise. Pistes : 0 eng « … » 2 canaux, 1 ? … Choisissez avec --audio-track N.`

- [ ] **Step 1: failing tests**

```python
def test_prefers_french_by_language(): ...          # [eng, fre] → index 1, no warning
def test_prefers_french_by_title_when_untagged(): ... # [None "English", None "VFF 5.1"] → index 1
def test_falls_back_to_first_with_warning(): ...    # [None, None] → index 0, warning contains "--audio-track"
def test_forced_out_of_range_lists_tracks(): ...
def test_probe_test_film(test_film):                # conftest fixture
    info = probe(test_film)
    assert abs(info.duration - 12.0) < 0.1 and [t.language for t in info.audio] == ["eng", "fre"]
def test_decode_window_length(test_film):
    assert len(decode_window(test_film, 1, 2.0, 3.0)) == pytest.approx(48000, abs=160)
def test_paths_with_spaces_and_accents(tmp_path): ... # film in "Films été/Le Dîner (1998).mkv"
def test_missing_ffmpeg_message(monkeypatch): ...   # shutil.which → None; message contains "brew install ffmpeg"
```

- [ ] **Step 2:** FAIL. **Step 3:** implement (`ffprobe -v error -print_format json -show_format -show_streams`). **Step 4:** PASS.
- [ ] **Step 5:** commit `feat: analyse du film et choix de la piste VF`.

---

### Task 6: cut snapping (pure logic)

**Files:** Create `src/podcleaner_clips/adjust.py`, `tests/test_adjust.py`

**Interfaces:**
- Consumes: `Settings` (task 4).
- Produces:
  - `@dataclass(frozen=True) class Word: text: str; start: float; end: float` (absolute times in the film).
  - `@dataclass(frozen=True) class Match: first: int; last: int; score: float` (indices in the word list).
  - `find_line(words: list[Word], line: str) -> list[Match]`: sorted by descending score.
  - `@dataclass(frozen=True) class Cut: start: float; end: float; method: str` (`"notes"`, `"whisper"`, `"claude"`) `; score: float | None; doubt: str | None` (reason in French, `None` when confident).
  - `@dataclass(frozen=True) class Decision: cut: Cut; needs_review: bool; matches: list[Match]`
  - `adjust_cut(words: list[Word], line: str, noted_start: float, noted_end: float, s: Settings) -> Decision`
  - `cut_from_words(words: list[Word], first: int, last: int, noted_start: float, noted_end: float, s: Settings) -> Cut`: reused by task 7 to apply Claude's opinion.

Algorithm:
- Normalization for comparison: lowercase, no accents, punctuation and apostrophes → space.
- `find_line`: for each position, windows of `n-2` to `n+2` words (`n` = words in the line), `rapidfuzz.fuzz.ratio` on the joined texts; keep the best window per start position, then drop windows that overlap a better-scored one.
- Sentence end: a word ending with `.`, `!`, `?`, `…`, or followed by a pause ≥ `sentence_gap_s`.
- `adjust_cut`:
  - best score < `score_min`, or line outside `[noted_start − adjust_max_s, noted_end + adjust_max_s]` → `Cut(noted_start, noted_end, "notes", score, "réplique introuvable")`.
  - The start only moves back when needed: `S = min(noted_start, start of the line)`. If `S` falls inside a word, move back to the first word of its sentence, or else to the start of that word; then `− pad_before_s`, without entering the previous word; never before `noted_start − adjust_max_s`. If `S` falls in a silence, keep it.
  - End is symmetrical: `E = max(noted_end, end of the line)`, moves forward to the sentence end, `+ pad_after_s`, without entering the next word; never after `noted_end + adjust_max_s`. If the 4 s limit falls inside a sentence, stop at the end of the last whole word before the limit and set `doubt = "fin de phrase au-delà de 4 s"`.
  - `needs_review = True` if `score_min ≤ score < score_sure`, or if two `Match` scores are within 5 points; the occurrence closest to `noted_start` is then chosen and `doubt` explains why.

- [ ] **Step 1: failing tests** (hand-written `Word` lists)

```python
def test_exact_line_snaps_to_sentence_bounds(): ...
    # "Bonjour. Il s'appelle Juste Leblanc. Ah bon ?"; notes 10.3 > 12.0 cut into "Il" and "Leblanc"
    # → start == start of "Il" - 0.10, end == end of "Leblanc." + 0.25, method "whisper", doubt None
def test_never_moves_inward(): ...         # notes already in silences around the sentence → unchanged
def test_never_cuts_a_word_at_4s_limit(): ... # 8 s sentence after the noted end → end = end of a whole word ≤ noted_end + 4, doubt set
def test_padding_does_not_enter_neighbour_word(): ... # previous word ends 0.05 s before → start == its end
def test_unrecognised_line_keeps_noted(): ...  # score < 50 → Cut(noted…, "notes", doubt="réplique introuvable")
def test_misheard_line_needs_review(): ...    # "Il s'appelle juste le blanc" vs "Juste Leblanc" → 50 ≤ score < 80, needs_review
def test_repeated_line_picks_closest_and_needs_review(): ...
def test_line_outside_window_is_ignored(): ... # line found 6 s before noted_start → method "notes"
```

- [ ] **Step 2:** FAIL. **Step 3:** implement. **Step 4:** PASS.
- [ ] **Step 5:** commit `feat: calage des coupes sur la réplique`.

---

### Task 7: transcription and Claude's opinion

**Files:** Create `src/podcleaner_clips/transcribe.py`, `src/podcleaner_clips/claude.py`, `tests/test_transcribe.py`, `tests/test_claude.py`

Load the `claude-api` skill before writing `claude.py`.

**Interfaces:**
- Consumes: `decode_window` (task 5), `Word`, `Decision`, `cut_from_words` (task 6), `fallback_abbreviation` (task 2), `Settings`.
- Produces:
  - `class Transcriber(Protocol): def words(self, audio: np.ndarray, offset: float) -> list[Word]`
  - `make_transcriber(model: str) -> Transcriber`: mlx-whisper on macOS arm64, faster-whisper (`compute_type="int8"`) elsewhere; `language="fr"`, `word_timestamps=True`; model loaded once per run, on first call. `offset` is added to the times to get absolute times.
  - `@dataclass(frozen=True) class ClaudeAdvice: kind: str; answer: str; reason: str; model: str` (written as is to the index).
  - `class ClaudeClient`: `available: bool` (key present and `claude_enabled`); `propose_abbreviation(title: str, film_file: str | None) -> tuple[str, ClaudeAdvice | None]`; `review_cut(words: list[Word], line: str, noted_start: float, noted_end: float, decision: Decision, s: Settings) -> tuple[Cut, ClaudeAdvice | None]`.

Rules:
- Abbreviation: expected answer `^[A-Z0-9]{2,6}$`; unavailable, network error or invalid answer → `fallback_abbreviation(title)` and `None`.
- Cut: send the numbered words with their times, the line, the noted timecodes and the occurrences found; structured answer (tool use) `{premier_mot: int, dernier_mot: int, raison: str}`; converted by `cut_from_words` with `method="claude"`. Out-of-range indices or a cut beyond ±4 s → `decision`'s cut is kept. Unavailable → `decision`'s cut, `doubt` kept.
- An API error never stops the run: a warning, then the fallback.

- [ ] **Step 1: failing tests** (`test_claude.py` with an injected fake Anthropic client, no network)

```python
def test_abbreviation_without_key_uses_initials(monkeypatch): ...  # no ANTHROPIC_API_KEY → ("DDC", None)
def test_abbreviation_invalid_answer_falls_back(): ...           # fake client answers "Le dîner" → "DDC"
def test_abbreviation_valid_answer(): ...                         # "DDC" → ("DDC", advice.kind == "abreviation")
def test_review_cut_applies_claude_choice(): ...                  # indices 3..7 → Cut.method == "claude"
def test_review_cut_rejects_out_of_bounds(): ...                  # index 999 → original cut
def test_api_error_falls_back_with_warning(): ...                 # fake client raises anthropic.APIError
```

And `test_transcribe.py` (marked `slow`, skipped without `say` on macOS): generate `say -v Thomas "Bonjour. Il s'appelle Juste Leblanc."`, transcribe, check that `find_line(words, "Il s'appelle Juste Leblanc")[0].score >= 80` and that times are increasing.
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
    "numero": 1, "replique": "...", "empreinte": "…",
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
def test_index_roundtrip_utf8(tmp_path): ...              # accented line read back identically, file readable as UTF-8
```

- [ ] **Step 2:** FAIL. **Step 3:** implement. **Step 4:** PASS.
- [ ] **Step 5:** commit `feat: index extraits.json et relance incrémentale`.

---

### Task 11: pipeline and `run` command

**Files:** Create `src/podcleaner_clips/pipeline.py`, `tests/test_pipeline.py`; Modify `cli.py`

**Interfaces:**
- Consumes: everything above.
- Produces:
  - `@dataclass(frozen=True) class RunOptions: notes: Path; transition: bool = True; audio: bool = True; video: bool = True; adjust: bool = True; dry_run: bool = False; audio_track: int | None = None; config: Path | None = None`
  - `run(opts: RunOptions, *, transcriber: Transcriber | None = None, claude: ClaudeClient | None = None, echo: Callable[[str], None] = typer.echo) -> FilmIndex | None` (injections for tests).
  - CLI: `podcleaner-clips run NOTES [--no-transition] [--audio-only | --video-only] [--no-adjust] [--dry-run] [--audio-track N] [--config PATH]`.

Flow: `require_ffmpeg` → `load_settings` → `read_notes` (line errors shown) → film found via `fichier:` (absolute, otherwise relative to the notes folder, otherwise to `dossier_films`; missing → `ClipsError` listing the places searched) → `probe` + `choose_audio_track` → abbreviation (from the notes, otherwise Claude/fallback then `write_abbreviation` unless `--dry-run`) → `plan_actions` → for each clip to do: window `[start − window_margin, end + window_margin]` clamped to `[0, duration]`, `transcriber.words`, `adjust_cut`, `review_cut` if `needs_review`; then renders; renames → `save_index` → summary.

Rules:
- `--audio-only` and `--video-only` together → `ClipsError`. `--video-only` still renders the WAV into a temporary file, deleted afterwards.
- `--no-adjust`: neither Whisper nor Claude for cuts, method `"notes"`.
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
- [ ] **Step 5:** **test-rapide** skill (written with `skill-creator`): generate a 20 s film with `make_test_film.py` (VF + original), a notes file with two clips, a temporary config, run `run --no-adjust` then `run`, and check names, durations (`ffprobe`), levels (-16 ± 1 LUFS, ≤ -1 dBTP) and the VF track (660 Hz sine dominant). **compat-windows** skill: run `check_windows_compat.py`, `require_ffmpeg`, then a `run --no-adjust` in a folder named `Été à l'écran/`; to do before each release.
- [ ] **Step 6:** README in English and French (`README.md`, `README.fr.md`): installation (uv, ffmpeg on macOS and Windows), `config init`, notes file format, options, outputs, optional Claude.
- [ ] **Step 7:** `uv run ruff check && uv run pytest`, then run the test-rapide skill → everything passes.
- [ ] **Step 8:** commit `docs: skills test rapide et compatibilité Windows, README`.

---

## Order and parallelism

1 → 2 → 3 → 4 → 5, then 6 (depends only on 4) and 8 (depends on 5) can proceed in parallel; 7 after 5 and 6; 9 after 8; 10 after 3, 6 and 7; 11 after everything; 12 last.

## Test data

- Generated by `scripts/make_test_film.py` for automated tests (no film in the repository).
- A real film with VF + original audio and a notes file with 3 or 4 clips in `samples/` (ignored by git) for task 11's manual test, ideally with a noisy scene and a 5.1 VF.
