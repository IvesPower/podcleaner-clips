# Automated movie clips: Podcleaner-clips
Initial design

[Français](spec.fr.md) · **English** — translated from the French original, which remains the reference.

Nov 6, 2026 · @Julien — revised Nov 9, 2026 from real viewing notes

## Context and goal

The goal is a command-line tool that cuts, from a film, the clips noted while watching it, and files them ready to be played live while recording the episode. Working name: podcleaner-clips.

The tool runs on macOS and Windows and will be published as open source, like podcleaner-editor. It stays usable without an account or an API key: Claude picks the film abbreviation and refines the cuts, but the tool has a fallback for every case.

Notes are taken quickly, during the film: timecodes are approximate (about ten seconds off) and the line is only a reference of a few words, not necessarily exact. The tool must find the scene and cut it cleanly despite that.

## Features

| Feature | What it does | Open source tools | Claude's contribution |
| --- | --- | --- | --- |
| Reading the notes | Reads the notes file filled in while watching: for each clip, a start timecode, a reference to the line and an end timecode | Regular expressions | None |
| Track selection | Always takes a French dub (VF) audio track; if there are several (VFF from France, VFQ from Québec), VFF by default (configurable); if no track is tagged French, takes the first one and says so | ffprobe | None |
| Finding the references | Finds each reference in the scene: first in the film's French subtitles if it has any, then in the Whisper transcription of the dub | ffmpeg (subtitles), faster-whisper or mlx-whisper (word timestamps), rapidfuzz | Choose the right occurrence when the reference is approximate or repeated |
| Cut adjustment | Keeps the noted scene, but snaps its start and end to sentence boundaries within ±15 s, without cutting a word, with every reference included | faster-whisper or mlx-whisper | Choose the scene's exact bounds so that it makes sense |
| Film abbreviation | Gives the film a short, stable abbreviation (e.g. "DDC" for Le Dîner de cons), kept for all its clips | None | Suggest the abbreviation; without an API key, the tool uses the title's initials |
| Clip audio | Fade-in and fade-out, transition sound at the start and the end, normalization to -16 LUFS and -1 dBTP | ffmpeg | None |
| Clip video | Same cut as the audio, black screen during the transition sound | ffmpeg | None |
| Clip index | Writes one JSON file per film with each clip, its reference, its duration and its files | None | None |

Command options:

- `--film PATH`: the film file, when the notes file does not give it.
- `--no-transition`: no transition sound, fades only.
- `--audio-only`: produce audio clips only.
- `--video-only`: produce video clips only.
- `--no-adjust`: cut exactly at the noted timecodes, without subtitles or Whisper.
- `--dry-run`: show the proposed cuts and file names without writing anything.

## Notes file

One text or Markdown file per film, written while watching. One line per clip, in this order: **start timecode, reference, end timecode**.

```markdown
# Le Dîner de cons
fichier: Le Diner de cons (1998).mkv
abreviation: DDC

12:34 il s'appelle Juste Leblanc 12:51
47:02 une bonne tête … de vainqueur 47:20
1:02:10 tu sais pas ce que tu rates 1:02:40

La scène du téléphone est trop longue pour un extrait.
```

The keys of the notes file stay in French (`fichier` = file, `abreviation` = abbreviation).

- **Timecodes**: `HH:MM:SS`, or `MM:SS` under an hour (`45:12` = 45 min 12 s). Common typos are accepted: `6;25` (semicolon), `25 min 30`. They are approximate: about ten seconds off is normal.
- **Reference**: a few words of the line, from memory, not necessarily exact. A long scene can have several fragments, separated by `…`, `...` or ` - `; each one must be inside the clip.
- **Optional header**: `# Title`, `fichier:` and `abreviation:`. Without `fichier:`, the film is given with `--film`. Without a title, the tool derives it from the film's file name (`The Night Before (2015) Bluray-1080p.mkv` → `The Night Before (2015)`).
- **Other lines**: any line that does not start and end with a timecode is ignored, so other notes can stay in the same file. The former form `- 00:12:34 > 00:12:51 | line` is still accepted.

The `abreviation` line is optional. If it is missing, the tool asks Claude for one and writes it into the file so that it no longer changes. Each clip's name starts with the first words of its reference: `DDC-01-il-s-appelle-juste-leblanc.wav`.

## Architecture

The program is a Python CLI that does all processing locally with ffmpeg and Whisper. Claude only steps in for the abbreviation and the choice of bounds, always optionally.

1. Read the notes file and the configuration.
2. Analyze the film with ffprobe: duration, audio and subtitle tracks, language of each track.
3. If the film has French text subtitles (other than "forced" subtitles), extract them once and look for each reference near the noted timecodes.
4. For each clip, extract the VF audio of the noted scene with 15 s of margin on each side, then transcribe it with word timestamps.
5. Find the references in the transcription (helped by the subtitles), then snap the start and end to sentence boundaries.
6. Final cut, fades, transition added, normalization, then audio and video export.
7. Write the JSON index and a summary in the terminal.

Paths are never hard-coded. One configuration file per person gives the episodes folder, the transition sound and the films folder. Julien and Franck each keep their own layout, on Mac as on Windows.

Points of attention:

- **Computation time.** Only the noted scene and 15 s on each side are transcribed. A full film is never transcribed.
- **Subtitles and dub differ.** Subtitles are often translated separately from the dub: they help locate the reference, but cuts are made on the dub's words transcribed by Whisper.
- **Music and sound effects.** Whisper makes more mistakes on a noisy scene. If a reference is found neither in the subtitles nor in the transcription, the tool keeps the noted timecodes (without cutting a word) and says so.
- **Mislabeled tracks.** Some .mkv files do not state the language of their tracks. The tool then lists the tracks found and lets you choose one with an option.
- **Reproducibility.** The chosen cuts and Claude's opinions are written to the index, so a run can be repeated identically.

## Outputs

Everything goes into `{episodes-folder}/{film-name}/`, with one subfolder per type:

```
Le Diner de cons/
  audio/
    DDC-01-il-s-appelle-juste-leblanc.wav
    DDC-02-une-bonne-tete-de-vainqueur.wav
  video/
    DDC-01-il-s-appelle-juste-leblanc.mp4
    DDC-02-une-bonne-tete-de-vainqueur.mp4
  extraits.json
```

- **Audio**: 48 kHz WAV, normalized to -16 LUFS and -1 dBTP, so that all clips play at the same volume live.
- **Video**: H.264 MP4 with AAC sound, same cut and same sound as the audio.
- **Index** (`extraits.json`): for each clip, the number, the reference, the noted and chosen timecodes, the duration and the file paths. This is the file the future live player will read.

A new run on the same film only rewrites the clips added or changed in the notes file.

## Out of scope, decisions and open questions

The first version does not include the live player, video transition effects or burning subtitles into the clips.

| Topic | Decision |
| --- | --- |
| Input formats | Mostly .mkv, also .avi and .mp4 |
| Clip list | One notes file per film; one line per clip: start timecode, reference, end timecode |
| Timecode format | `HH:MM:SS`, or `MM:SS` under an hour (`45:12`), optional decimals; `;` and `25 min 30` tolerated |
| Reference | A few words of the line, approximate; several fragments separated by `…`, `...` or ` - ` |
| Clip bounds | The clip keeps the noted scene. Start and end are snapped to sentence boundaries within ±15 s of the noted timecodes, without cutting a word, and every reference is included: better a little margin than a cut-off line. References not found: noted timecodes kept (without cutting a word) and flagged |
| Locating | French text subtitles if any (other than "forced"), then Whisper on the scene ±15 s; Whisper only otherwise |
| Claude's role | With a key, Claude picks each clip's bounds from the transcription; its answer is checked. Without a key, a simple rule: the sentence boundary closest to each noted timecode |
| Naming | `{abbreviation}-{number}-{first-words-of-the-reference}.{format}` |
| Abbreviation | Suggested by Claude, title initials without an API key, then frozen in the notes file |
| Language | Always a VF track, for audio and video alike; VFF preferred when there is also a VFQ (configurable) |
| Fades | 0.7 s at the start and the end |
| Transition sound | Starts just before the clip; the fade-in happens during its end, and the film sound is at 100% once the transition is over. The same in reverse at the end of the clip |
| Video transition | Black screen during the transition sound, effects to be added later |
| Output formats | 48 kHz WAV at -16 LUFS for audio, H.264 MP4 for video |
| Paths | One configuration file per person, no hard-coded path |

No open question at this stage: the design is complete enough to start.

## Tools for developing the project

The project reuses the podcleaner-editor environment in Claude Code: Superpowers, feature-dev, python-development, skill-creator, the Ruff and pytest hooks, and the GitHub and Context7 MCP servers. The Hugging Face MCP is not useful here. graphify gives Claude a graph of the code to keep each session's context small.

Skills to write for the project, versioned in `.claude/skills/`:

- **Quick test**: cuts two clips from a short test video file, a .mkv with a VF and an original-language track, and checks names, durations and levels.
- **Windows compatibility**: checks paths, the presence of ffmpeg and the encoding of accented file names before each release.

A `CLAUDE.md` file at the root restates the decisions of this document.
