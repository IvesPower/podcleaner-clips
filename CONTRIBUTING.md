# Contributing

[Français](CONTRIBUTING.fr.md) · **English**

## Workflow

- `main` is protected: nobody pushes to it directly, and force-pushes and deletion are blocked.
- Every change goes through a pull request. A PR from a contributor is merged only after the maintainer approves it (see [CODEOWNERS](.github/CODEOWNERS)).
- Work on a branch named after its type: `feat/notes-parser`, `fix/track-selection`, `docs/readme`.

## Commit messages

Commits follow [Conventional Commits](https://www.conventionalcommits.org/), written **in English, then in French**, so that everyone can read the history:

```
<type>(<optional scope>): <English summary> / <résumé en français>
```

An optional body has one paragraph in English, a blank line, then the same paragraph in French.

Types: `feat`, `fix`, `docs`, `test`, `refactor`, `perf`, `build`, `ci`, `chore`. A breaking change adds `!` after the type (`feat!: …`) or a `BREAKING CHANGE:` footer.

Examples:

```
feat(notes): read timecodes with milliseconds / lire les timecodes avec millisecondes
fix(audio): keep the dialogue when downmixing a 5.1 track / garder les dialogues au downmix d'une piste 5.1
docs: translate the specification / traduire le cahier des charges
```

## Pull request title and description

- The **title** uses the same format as a commit title: `type: English / français`.
- The **description** is written entirely in English first, then entirely in French, separated by `---`.
- Each language starts with a **TL;DR**: 1 to 3 plain sentences saying what the PR changes and why, understandable without reading the code.

The [PR template](.github/pull_request_template.md) is filled in automatically when you open a PR.

## Documentation

Docs exist in English and French. English files have no suffix (`README.md`), French files end in `.fr.md` (`README.fr.md`). When you change one, update the other in the same PR, or say in the PR that the translation is pending.

## Working with Claude Code (graphify)

The repository ships a [graphify](https://github.com/Graphify-Labs/graphify) setup for Claude Code: a knowledge graph of the code that Claude queries instead of re-reading files, which keeps each session's context smaller. The code is parsed locally with tree-sitter; nothing is sent over the network.

```bash
uv tool install graphifyy    # once per machine (the package name has two y's)
graphify update .            # build or refresh the graph in graphify-out/ (not committed)
graphify hook install        # optional: rebuild the graph after each commit and checkout
```

The Claude Code hooks in `.claude/settings.json` call `graphify`: without it installed, Claude Code shows a non-blocking hook error and works as usual.

## Before opening a PR

```bash
uv run ruff check
uv run pytest
```

Both must pass on macOS and Windows; CI checks both.
