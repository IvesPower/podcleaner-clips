# podcleaner-clips

[Français](README.fr.md) · **English**

A command-line tool that cuts the movie clips you noted while watching a film, and files them ready to be played live while recording a podcast episode.

## What it does

While watching, you write one notes file per film, one line per clip: the start timecode, a few words of the line, the end timecode.

```markdown
# Avengers
file: Avengers (2012) Bluray-1080p.mkv

5:20 monsieur, veuillez poser votre lance 5:30
7:00 la fourmi n'est pas en conflit avec la botte 7:10
21:45 on m'a dit qu'on avait gagné la guerre … on ne m'a pas dit ce qu'on avait perdu 21:58
```

The full notes file of this example is in [`examples/avengers.md`](examples/avengers.md).

Then `pclips run notes.md`:

- picks the French dub (VF) audio track, the France one (VFF) when there is also a Quebec one (VFQ); it warns you if no track is tagged French;
- finds each line in the French subtitles when the film has some, then in the dub with Whisper (only around each clip, never the whole film);
- moves the start and the end to sentence boundaries within 15 s of your timecodes, never cutting a word, with every noted fragment inside;
- adds 0.7 s fades and your transition sound before and after the clip, then normalizes to -16 LUFS / -1 dBTP;
- writes a 48 kHz WAV, an H.264 MP4 (black screen, or your transition video, during the transition, the picture fading in from black and out to black with the sound) and a `clips.json` index of the chosen cuts;
- on later runs, only redoes the clips you added or changed, and renames the files of clips that moved.

```
Avengers/
  audio/AV-03-on-m-a-dit-qu-on-avait-gagne-la-guerre.wav
  video/AV-03-on-m-a-dit-qu-on-avait-gagne-la-guerre.mp4
  clips.json
```

## Install

You need:

- macOS or Windows;
- [uv](https://docs.astral.sh/uv/) (it installs the right Python, 3.11 or 3.12);
- [ffmpeg](https://ffmpeg.org/) on the `PATH`: `brew install ffmpeg` on macOS, `winget install ffmpeg` on Windows.

```bash
uv tool install git+https://github.com/IvesPower/podcleaner-clips
pclips --version
```

This installs two names for the same command, usable from any folder: `podcleaner-clips` and its short form `pclips`. If the command is not found, run `uv tool update-shell` and open a new terminal (it adds uv's tool folder, `~/.local/bin`, to the `PATH`). Update with `uv tool upgrade podcleaner-clips`.

| Command | Does |
| --- | --- |
| `pclips init` | Creates your configuration file |
| `pclips run notes.md` | Cuts the clips noted for a film |
| `pclips config` | Shows the configuration as read (`--path`: only where the file is) |
| `pclips --version` | Shows the version |

`pclips` alone, `init` and `run` start with the tool's name drawn in pixels. It is never shown when the output goes to a file or another program; turn it off with `pclips --no-banner …` or `PODCLEANER_CLIPS_NO_BANNER=1`.

The first run that locates lines downloads the Whisper model (`large-v3-turbo`, over 1 GB). On a Mac with Apple Silicon it runs with MLX; elsewhere with faster-whisper on the CPU.

## Configure

Each person has their own configuration file. Create it by answering a few questions:

```bash
pclips init
```

It asks for the folder where clips are stored (required; it offers to create it), the folder where your films are, the transition sound and an optional transition video, the preferred dub (VFF or VFQ) and whether to use Claude, saying whether Claude Code or an API key was found. Paths can be pasted or dragged into the terminal. Run `pclips init` again to change your answers: the current values are offered as defaults, and the file is replaced only after you confirm.

The file is written to `~/Library/Application Support/podcleaner-clips/config.toml` on macOS and `%LOCALAPPDATA%\podcleaner-clips\config.toml` on Windows (`--config` or the `PODCLEANER_CLIPS_CONFIG` variable point elsewhere; `pclips config --path` prints it). The other settings (`[adjust]`, `[audio]`, …) are in the file, commented: remove the `#` to change one. Check what is read with `pclips config`. Without a terminal, or with `pclips init --no-input`, the commented file is written without questions.

Files written for version 0.1.0, with French names (`dossier_episodes`, `fichier:`, `abreviation:`, `extraits.json`…), are still read: the tool lists the names to change, and replaces `extraits.json` with `clips.json` on the next run without rendering the clips again.

## The notes file

- One line per clip: `start reference end`. Timecodes as `HH:MM:SS` or `MM:SS` (`45:12` is 45 min 12 s); `6;25` and `25 min 30` are understood too.
- Timecodes can be about 10 s off and the reference only a few words, even misspelled. Separate several fragments of a long scene with `…`, `...` or ` - `.
- Header lines, before the first clip: `# Title`, `file: <film>` (absolute path, or relative to the notes file or to `films_dir`), `abbreviation: AV` (written by the tool if missing).
- Any other line is ignored, so you can keep other notes in the same file. The older form `- 00:12:34 > 00:12:51 | line` is accepted.

## Run

```bash
pclips run notes.md
```

| Option | Effect |
| --- | --- |
| `--dry-run` | Find the cuts and show them, write nothing |
| `--film PATH` | Use this film instead of `file:` |
| `--no-transition` | Fades only, no transition sound, no black screen or transition video |
| `--audio-only` / `--video-only` | Only the WAV files / only the MP4 files |
| `--no-adjust` | Cut exactly at the noted timecodes (no subtitles, Whisper or Claude) |
| `--audio-track N` | Use audio track N (from 0) when tracks are mislabelled |
| `--config PATH` | Use another configuration file |

The summary shows, for each clip, the noted and chosen timecodes, the length and what was done (`new`, `changed`, `unchanged`, `renamed`). A `⚠` line flags a doubt: line not found (the noted timecodes are kept) or found but unsure. Listen to those first. Files of clips removed from the notes are listed, never deleted. The exit code is 1 if a clip failed (for example, it ends after the film).

## Claude, optional

No account is needed. When Claude is available, it suggests the film's abbreviation and chooses the bounds of each clip from the transcription; its answers are checked (within 15 s of your timecodes, every fragment inside) and recorded in `clips.json`. Without Claude, or if it cannot be reached, the abbreviation is the title's initials and the cut is the sentence boundary closest to each noted timecode.

The tool reaches Claude in one of two ways, chosen with `backend` in `[claude]`:

- **Your Claude subscription** (Pro or Max), through the [Claude Code](https://claude.com/claude-code) command line: install it, then run `claude auth login` once. This is tried first.
- **An API key**: set `ANTHROPIC_API_KEY` (billed per use on the Anthropic API).

`backend = "auto"` (the default) uses the subscription if Claude Code is installed and logged in, else the API key if there is one, else no Claude. `"cli"` and `"api"` force one of the two, `"off"` never asks Claude. The first lines of each run say which one answers.

## Contributing

Contributions are welcome. Read [CONTRIBUTING.md](CONTRIBUTING.md): every change goes through a pull request reviewed by the maintainer, and commits follow [Conventional Commits](https://www.conventionalcommits.org/). The [specification](docs/spec.md) and the [implementation plan](docs/superpowers/plans/2026-11-06-podcleaner-clips-v1.md) explain the choices made.

```bash
git clone https://github.com/IvesPower/podcleaner-clips.git
cd podcleaner-clips
uv sync                  # the project and its tools
uv run pclips            # the command, from this clone
uv run pytest            # fast tests (no Whisper, no network)
uv run pytest -m slow    # tests that load a Whisper model
uv run ruff check
```

## License

[MIT](LICENSE)
