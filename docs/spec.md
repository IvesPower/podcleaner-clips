# Automated movie clips: Podcleaner-clips
Initial design

[Français](spec.fr.md) · **English** — translated from the French original, which remains the reference.

Nov 6, 2026 · @Julien

## Context and goal

The goal is a command-line tool that cuts, from a film, the clips noted while watching it, and files them ready to be played live while recording the episode. Working name: podcleaner-clips.

The tool runs on macOS and Windows and will be published as open source, like podcleaner-editor. It stays usable without an account or an API key: Claude picks the film abbreviation and refines the cuts, but the tool has a fallback for every case.

## Features

| Feature | What it does | Open source tools | Claude's contribution |
| --- | --- | --- | --- |
| Reading the notes | Reads the .md file filled in while watching: start and end timecodes, line of each clip | Markdown parser | None |
| Track selection | Always takes the French dub (VF) audio track; if no track is tagged French, takes the first one and says so | ffprobe | None |
| Cut adjustment | Transcribes a window of about 30 s around the noted timecodes, finds the line and fits the clip to it: from the start of the sentence where it begins to the end of the sentence where it ends, without cutting a word | faster-whisper or mlx-whisper (word timestamps), rapidfuzz | Choose the line and the cut bounds, especially when the line is poorly transcribed, repeated, or when several endings are possible |
| Film abbreviation | Gives the film a short, stable abbreviation (e.g. "DDC" for Le Dîner de cons), kept for all its clips | None | Suggest the abbreviation; without an API key, the tool uses the title's initials |
| Clip audio | Fade-in and fade-out, transition sound at the start and the end, normalization to -16 LUFS and -1 dBTP | ffmpeg | None |
| Clip video | Same cut as the audio, black screen during the transition sound | ffmpeg | None |
| Clip index | Writes one JSON file per film with each clip, its line, its duration and its files | None | None |

Command options:

- `--no-transition`: no transition sound, fades only.
- `--audio-only`: produce audio clips only.
- `--video-only`: produce video clips only.
- `--no-adjust`: cut exactly at the noted timecodes, without Whisper.
- `--dry-run`: show the proposed cuts and file names without writing anything.

## Notes file

One .md file per film, written while watching. One line per clip: start timecode, end timecode, line. Timecodes are written `HH:MM:SS`, or `MM:SS` under an hour (`45:12` = 45 min 12 s), and can be approximate: up to about 30 s off, they are used to find the line, which sets the clip's real bounds. Lines that do not follow this format are ignored, so other notes can stay in the same file.

```markdown
# Le Dîner de cons
fichier: Le Diner de cons (1998).mkv
abreviation: DDC

## Extraits
- 00:12:34 > 00:12:51 | Il s'appelle Juste Leblanc
- 00:47:02 > 00:47:20 | Il a une bonne tête de vainqueur

## Notes libres
La scène du téléphone est trop longue pour un extrait.
```

The keys of the notes file stay in French (`fichier` = file, `abreviation` = abbreviation, `Extraits` = clips, `Notes libres` = free notes).

The `abreviation` line is optional. If it is missing, the tool asks Claude for one and writes it into the file so that it no longer changes. Each clip's name starts with the first words of its line: `DDC-01-il-s-appelle-juste-leblanc.wav`.

## Architecture

The program is a Python CLI that does all processing locally with ffmpeg and Whisper. Claude only steps in for the abbreviation and doubtful cuts, always optionally.

1. Read the notes file and the configuration.
2. Analyze the film with ffprobe: duration, audio tracks, language of each track.
3. For each clip, extract the VF audio with a margin of about 30 s on each side of the noted timecodes.
4. Transcribe this window with word timestamps, find the line, snap the start and end.
5. Final cut, fades, transition added, normalization, then audio and video export.
6. Write the JSON index and a summary in the terminal.

Paths are never hard-coded. One configuration file per person gives the episodes folder, the transition sound and the films folder. Julien and Franck each keep their own layout, on Mac as on Windows.

Points of attention:

- **Computation time.** Only the window around each clip is transcribed, about a minute each time. A full film is never transcribed.
- **Music and sound effects.** Whisper makes more mistakes on a noisy scene. If the line is not found, the tool keeps the noted timecodes and says so.
- **Mislabeled tracks.** Some .mkv files do not state the language of their tracks. The tool then lists the tracks found and lets you choose one with an option.
- **Reproducibility.** The chosen cuts and Claude's opinions are written to the index, so a run can be repeated identically.

## Outputs

Everything goes into `{episodes-folder}/{film-name}/`, with one subfolder per type:

```
Le Diner de cons/
  audio/
    DDC-01-il-s-appelle-juste-leblanc.wav
    DDC-02-il-a-une-bonne-tete-de-vainqueur.wav
  video/
    DDC-01-il-s-appelle-juste-leblanc.mp4
    DDC-02-il-a-une-bonne-tete-de-vainqueur.mp4
  extraits.json
```

- **Audio**: 48 kHz WAV, normalized to -16 LUFS and -1 dBTP, so that all clips play at the same volume live.
- **Video**: H.264 MP4 with AAC sound, same cut and same sound as the audio.
- **Index** (`extraits.json`): for each clip, the number, the line, the noted and chosen timecodes, the duration and the file paths. This is the file the future live player will read.

A new run on the same film only rewrites the clips added or changed in the notes file.

## Out of scope, decisions and open questions

The first version does not include the live player, video transition effects or subtitles.

| Topic | Decision |
| --- | --- |
| Input formats | Mostly .mkv, also .avi and .mp4 |
| Clip bounds | The noted timecodes are only used to locate the line (tolerance of about 30 s). The clip is fitted to the line: start of the sentence where it begins, end of the sentence where it ends, at most 4 s of context on each side of the line, without cutting a word: better a little margin than a cut-off line. Line not found: noted timecodes kept and flagged |
| Timecode format | `HH:MM:SS`, or `MM:SS` under an hour (`45:12`), optional decimals |
| Clip list | One .md notes file per film |
| Naming | `{abbreviation}-{number}-{first-words-of-the-line}.{format}` |
| Abbreviation | Suggested by Claude, title initials without an API key, then frozen in the notes file |
| Language | Always the VF track, for audio and video alike |
| Fades | 0.7 s at the start and the end |
| Transition sound | Starts just before the clip; the fade-in happens during its end, and the film sound is at 100% once the transition is over. The same in reverse at the end of the clip |
| Video transition | Black screen during the transition sound, effects to be added later |
| Output formats | 48 kHz WAV at -16 LUFS for audio, H.264 MP4 for video |
| Paths | One configuration file per person, no hard-coded path |

No open question at this stage: the design is complete enough to start.

## Tools for developing the project

The project reuses the podcleaner-editor environment in Claude Code: Superpowers, feature-dev, python-development, skill-creator, the Ruff and pytest hooks, and the GitHub and Context7 MCP servers. The Hugging Face MCP is not useful here.

Skills to write for the project, versioned in `.claude/skills/`:

- **Quick test**: cuts two clips from a short test video file, a .mkv with a VF and an original-language track, and checks names, durations and levels.
- **Windows compatibility**: checks paths, the presence of ffmpeg and the encoding of accented file names before each release.

A `CLAUDE.md` file at the root restates the decisions of this document.
