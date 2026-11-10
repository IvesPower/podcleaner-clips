# podcleaner-clips

[Français](README.fr.md) · **English**

A command-line tool that cuts the movie clips you noted while watching a film, and files them ready to be played live while recording a podcast episode.

## What it does

While watching, you write one notes file per film, one line per clip: the start timecode, a few words of the line, the end timecode.

```markdown
# The Night Before
fichier: The Night Before (2015) Bluray-1080p.mkv

2:35 d'une fabuleuse soirée incroyable 2:51
27:15 ce bébé c'est une connerie 27:37
43:00 si je veux la sucer … Isaac va sucer 44:08
```

Then `podcleaner-clips run notes.md`:

- picks the French dub (VF) audio track, the France one (VFF) when there is also a Quebec one (VFQ); it warns you if no track is tagged French;
- finds each line in the French subtitles when the film has some, then in the dub with Whisper (only around each clip, never the whole film);
- moves the start and the end to sentence boundaries within 15 s of your timecodes, never cutting a word, with every noted fragment inside;
- adds 0.7 s fades and your transition sound before and after the clip, then normalizes to -16 LUFS / -1 dBTP;
- writes a 48 kHz WAV, an H.264 MP4 (black screen during the transition) and an `extraits.json` index of the chosen cuts;
- on later runs, only redoes the clips you added or changed, and renames the files of clips that moved.

```
The Night Before (2015)/
  audio/NB-08-ce-bebe-c-est-une-connerie.wav
  video/NB-08-ce-bebe-c-est-une-connerie.mp4
  extraits.json
```

## Install

You need:

- macOS or Windows;
- [uv](https://docs.astral.sh/uv/) (it installs the right Python, 3.11 or 3.12);
- [ffmpeg](https://ffmpeg.org/) on the `PATH`: `brew install ffmpeg` on macOS, `winget install ffmpeg` on Windows.

```bash
git clone https://github.com/IvesPower/podcleaner-clips.git
cd podcleaner-clips
uv sync
uv run podcleaner-clips version
```

The first run that locates lines downloads the Whisper model (`large-v3-turbo`, over 1 GB). On a Mac with Apple Silicon it runs with MLX; elsewhere with faster-whisper on the CPU.

## Configure

Each person has their own configuration file. Create it, then open it:

```bash
uv run podcleaner-clips config init
```

It is created in `~/Library/Application Support/podcleaner-clips/config.toml` on macOS and in `%LOCALAPPDATA%\podcleaner-clips\config.toml` on Windows (`--config` or the `PODCLEANER_CLIPS_CONFIG` variable point elsewhere). Remove the `#` in front of at least the two lines below. On Windows, write paths with `/` (`"C:/Podcast/Episodes"`) or between single quotes (`'C:\Podcast\Episodes'`): a `\` between double quotes is an escape sequence in TOML.

```toml
dossier_episodes = "~/Podcast/Episodes"           # where clips are stored, one folder per film
son_transition = "~/Podcast/sons/transition.wav"  # played before and after each clip
```

Optional: `dossier_films` (where to look for a film named in the notes), `doublage_prefere = "VFQ"`, and the `[ajustement]`, `[son]` and `[claude]` sections, all commented in the file. Check what is read with `uv run podcleaner-clips config show`.

## The notes file

- One line per clip: `start reference end`. Timecodes as `HH:MM:SS` or `MM:SS` (`45:12` is 45 min 12 s); `6;25` and `25 min 30` are understood too.
- Timecodes can be about 10 s off and the reference only a few words, even misspelled. Separate several fragments of a long scene with `…`, `...` or ` - `.
- Header lines, before the first clip: `# Title`, `fichier: <film>` (absolute path, or relative to the notes file or to `dossier_films`), `abreviation: NB` (written by the tool if missing).
- Any other line is ignored, so you can keep other notes in the same file. The older form `- 00:12:34 > 00:12:51 | line` is accepted.

## Run

```bash
uv run podcleaner-clips run notes.md
```

| Option | Effect |
| --- | --- |
| `--dry-run` | Find the cuts and show them, write nothing |
| `--film PATH` | Use this film instead of `fichier:` |
| `--no-transition` | Fades only, no transition sound and no black screen |
| `--audio-only` / `--video-only` | Only the WAV files / only the MP4 files |
| `--no-adjust` | Cut exactly at the noted timecodes (no subtitles, Whisper or Claude) |
| `--audio-track N` | Use audio track N (from 0) when tracks are mislabelled |
| `--config PATH` | Use another configuration file |

The summary shows, for each clip, the noted and chosen timecodes, the length and what was done (`new`, `changed`, `unchanged`, `renamed`). A `⚠` line flags a doubt: line not found (the noted timecodes are kept) or found but unsure. Listen to those first. Files of clips removed from the notes are listed, never deleted. The exit code is 1 if a clip failed (for example, it ends after the film).

## Claude, optional

No account is needed. If `ANTHROPIC_API_KEY` is set, Claude suggests the film's abbreviation and chooses the bounds of each clip from the transcription; its answers are checked (within 15 s of your timecodes, every fragment inside) and recorded in `extraits.json`. Without a key, or if Claude cannot be reached, the abbreviation is the title's initials and the cut is the sentence boundary closest to each noted timecode. Turn it off with `actif = false` in `[claude]`.

## Contributing

Contributions are welcome. Read [CONTRIBUTING.md](CONTRIBUTING.md): every change goes through a pull request reviewed by the maintainer, and commits follow [Conventional Commits](https://www.conventionalcommits.org/). The [specification](docs/spec.md) and the [implementation plan](docs/superpowers/plans/2026-11-06-podcleaner-clips-v1.md) explain the choices made.

```bash
uv run pytest            # fast tests (no Whisper, no network)
uv run pytest -m slow    # tests that load a Whisper model
uv run ruff check
```

## License

[MIT](LICENSE)
