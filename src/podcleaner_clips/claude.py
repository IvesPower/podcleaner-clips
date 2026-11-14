"""Claude's opinion on the abbreviation and the clip bounds, always with a fallback.

Claude is reached through the Claude Code CLI (a Claude subscription) or the API (an
ANTHROPIC_API_KEY), as `[claude] backend` says. With neither, with Claude turned off, on an
error or on an answer that does not pass the checks, the result is the one computed without
Claude.
"""

import json
import os
import re
import shutil
import subprocess
import tempfile
from collections.abc import Callable
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

import anthropic

from podcleaner_clips.adjust import Cut, Decision, Word, bounds_ok, cut_from_words
from podcleaner_clips.config import Settings
from podcleaner_clips.naming import fallback_abbreviation, format_tc

_ABBREVIATION = re.compile(r"^[A-Z0-9]{2,6}$")
_MAX_TOKENS = 16000

_ABBREVIATION_SCHEMA = {
    "type": "object",
    "properties": {"abbreviation": {"type": "string"}, "reason": {"type": "string"}},
    "required": ["abbreviation", "reason"],
    "additionalProperties": False,
}
_BOUNDS_SCHEMA = {
    "type": "object",
    "properties": {
        "first_word": {"type": "integer"},
        "last_word": {"type": "integer"},
        "reason": {"type": "string"},
    },
    "required": ["first_word", "last_word", "reason"],
    "additionalProperties": False,
}

_ABBREVIATION_SYSTEM = (
    "You name the clip files of a French podcast about films. Each film gets a short "
    "abbreviation used as the file name prefix: 2 to 6 characters, uppercase letters A-Z or "
    "digits only, no spaces or accents. Prefer the abbreviation fans already use for the film, "
    "otherwise the initials of the significant words of its title. Give a one-sentence reason."
)
_BOUNDS_SYSTEM = (
    "You pick the start and end of a clip cut from a French-dubbed film, to be played live "
    "during a podcast recording. While watching, the host noted a start timecode, a few words "
    "of the line (not always exact, possibly several fragments) and an end timecode. The "
    "timecodes are approximate: up to about 15 seconds off. The clip must keep the whole noted "
    "scene: start at the beginning of a sentence, end at the end of a sentence, never in the "
    "middle of a line, and include every found fragment. Some margin is better than a cut-off "
    "line. Answer with the index of the first and last word of the clip, taken from the "
    "numbered transcript, and a one-sentence reason in English."
)


@dataclass(frozen=True)
class ClaudeAdvice:
    kind: str  # "abbreviation" or "bounds"
    answer: str
    reason: str
    model: str
    via: str = "api"  # "cli" (Claude Code) or "api"


_CLI_TIMEOUT_S = 180
# Runs a command: (args, stdin text, timeout) → completed process (text output).
Runner = Callable[[list[str], str, float], subprocess.CompletedProcess]


def _run(args: list[str], stdin: str, timeout: float) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env.pop("ANTHROPIC_API_KEY", None)  # the CLI must use the subscription, not the key
    with tempfile.TemporaryDirectory(prefix="podcleaner-clips-") as cwd:  # no CLAUDE.md
        return subprocess.run(
            args,
            input=stdin,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            cwd=cwd,
            env=env,
            check=False,
        )


def find_cli() -> str | None:
    """Path of the Claude Code CLI (`claude`, `claude.exe` or `claude.cmd`), if installed.

    Looks in PATH, then where the Claude Code installers put it: the terminal that runs this
    tool does not always have that folder in its PATH.
    """
    found = shutil.which("claude")
    if found:
        return found
    home = Path.home()
    for folder in (home / ".local" / "bin", home / ".claude" / "local"):
        found = shutil.which("claude", path=str(folder))
        if found:
            return found
    return None


def cli_logged_in(cli: str, runner: Runner = _run) -> bool | None:
    """True or False from `claude auth status`; None if it cannot tell."""
    try:
        done = runner([cli, "auth", "status", "--json"], "", 30)
        return bool(json.loads(done.stdout)["loggedIn"])
    except (OSError, subprocess.SubprocessError, ValueError, KeyError, TypeError):
        return None


class ClaudeClient:
    """Asks Claude when it is available; `warnings` collects the errors met on the way.

    `client` (an Anthropic client) or `cli` (path of the Claude Code CLI) skip the detection.
    """

    def __init__(
        self,
        s: Settings,
        client: Any = None,
        *,
        cli: str | None = None,
        runner: Runner = _run,
    ) -> None:
        self.model = s.claude_model
        self.warnings: list[str] = []
        self._backend = s.claude_backend
        off = self._backend == "off" or not s.claude_enabled
        self._client = None if off else client
        self._cli = None if off else cli
        self._runner = runner
        self._resolved = off or client is not None or cli is not None
        self.via: str | None = None
        if self._client is not None:
            self.via = "api"
        elif self._cli is not None:
            self.via = "cli"

    def _resolve(self) -> None:
        """Picks the backend the first time Claude is needed (a CLI check costs a process)."""
        self._resolved = True
        backend = self._backend
        if backend == "off":
            return
        if backend in ("auto", "cli"):
            cli = find_cli()
            logged_in = cli_logged_in(cli, self._runner) if cli else False
            if cli and logged_in is not False:
                self._cli, self.via = cli, "cli"
                return
            if backend == "cli":
                self.warnings.append(
                    "Claude Code is not installed; using the fallback."
                    if not cli
                    else "Claude Code is not logged in (run: claude auth login); "
                    "using the fallback."
                )
                return
        if os.environ.get("ANTHROPIC_API_KEY"):
            self._client, self.via = anthropic.Anthropic(), "api"
        elif backend == "api":
            self.warnings.append("ANTHROPIC_API_KEY is not set; using the fallback.")

    @property
    def available(self) -> bool:
        if not self._resolved:
            self._resolve()
        return self.via is not None

    def describe(self) -> str:
        """One line for the run header: who answers, if anyone."""
        if not self.available:
            return "not used (fallback without Claude)"
        where = "Claude Code CLI, your subscription" if self.via == "cli" else "API key"
        return f"{self.model} ({where})"

    def _advice(self, kind: str, answer: str, reason: Any) -> ClaudeAdvice:
        return ClaudeAdvice(kind, answer, str(reason or ""), self.model, self.via or "api")

    def _ask(self, system: str, prompt: str, schema: dict) -> dict | None:
        """Claude's JSON answer, or None (with a warning) if there is none to use."""
        if self.via == "cli":
            return self._ask_cli(system, prompt, schema)
        return self._ask_api(system, prompt, schema)

    def _ask_cli(self, system: str, prompt: str, schema: dict) -> dict | None:
        args = [
            self._cli,
            "-p",
            "--output-format", "json",
            "--model", self.model,
            "--system-prompt", system,
            "--json-schema", json.dumps(schema),
            "--tools", "",
            "--no-session-persistence",
            "--setting-sources", "",
            "--strict-mcp-config",
        ]  # fmt: skip
        try:
            done = self._runner(args, prompt, _CLI_TIMEOUT_S)
        except subprocess.TimeoutExpired:
            return self._cli_failed(f"no answer after {_CLI_TIMEOUT_S} s")
        except OSError as exc:
            return self._cli_failed(str(exc))
        try:
            out = json.loads(done.stdout)
        except json.JSONDecodeError:
            detail = (done.stderr or done.stdout).strip().splitlines()
            return self._cli_failed(detail[-1] if detail else f"exit code {done.returncode}")
        if not isinstance(out, dict) or out.get("is_error"):
            message = out.get("result") if isinstance(out, dict) else None
            return self._cli_failed(str(message or "error"))
        data = out.get("structured_output")
        if not isinstance(data, dict):
            try:
                data = json.loads(out.get("result") or "")
            except json.JSONDecodeError:
                self.warnings.append("Claude's answer is not valid JSON; using the fallback.")
                return None
        return data if isinstance(data, dict) else None

    def _cli_failed(self, reason: str) -> None:
        """Stops asking for this run: the same error would come back for every clip."""
        self.warnings.append(f"Claude Code did not answer ({reason}); using the fallback.")
        self.via = None
        return None

    def _ask_api(self, system: str, prompt: str, schema: dict) -> dict | None:
        try:
            response = self._client.messages.create(
                model=self.model,
                max_tokens=_MAX_TOKENS,
                system=system,
                messages=[{"role": "user", "content": prompt}],
                output_config={"format": {"type": "json_schema", "schema": schema}},
            )
        except anthropic.APIError as exc:
            self.warnings.append(f"Claude could not be reached ({exc}); using the fallback.")
            return None
        if response.stop_reason != "end_turn":
            self.warnings.append(
                f"Claude did not answer ({response.stop_reason}); using the fallback."
            )
            return None
        text = next((b.text for b in response.content if b.type == "text"), "")
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            self.warnings.append("Claude's answer is not valid JSON; using the fallback.")
            return None
        return data if isinstance(data, dict) else None

    def propose_abbreviation(
        self, title: str, film_file: str | None
    ) -> tuple[str, ClaudeAdvice | None]:
        fallback = fallback_abbreviation(title)
        if not self.available:
            return fallback, None
        prompt = f"Film title: {title}"
        if film_file:
            prompt += f"\nFilm file name: {film_file}"
        data = self._ask(_ABBREVIATION_SYSTEM, prompt, _ABBREVIATION_SCHEMA)
        if data is None:
            return fallback, None
        abbr = data.get("abbreviation")
        if not isinstance(abbr, str) or not _ABBREVIATION.match(abbr):
            return fallback, None
        return abbr, self._advice("abbreviation", abbr, data.get("reason"))

    def choose_bounds(
        self,
        words: list[Word],
        reference: str,
        decision: Decision,
        noted_start: float,
        noted_end: float,
        s: Settings,
    ) -> tuple[Cut, ClaudeAdvice | None]:
        """Claude's bounds if they pass `bounds_ok`, else the cut of `decision`."""
        if not self.available or not words:
            return decision.cut, None
        prompt = _bounds_prompt(words, reference, decision, noted_start, noted_end, s)
        data = self._ask(_BOUNDS_SYSTEM, prompt, _BOUNDS_SCHEMA)
        if data is None:
            return decision.cut, None
        first, last = data.get("first_word"), data.get("last_word")
        if not isinstance(first, int) or not isinstance(last, int):
            return decision.cut, None
        advice = self._advice("bounds", f"{first}-{last}", data.get("reason"))
        if not bounds_ok(words, first, last, decision.matches, noted_start, noted_end, s):
            return decision.cut, advice
        cut = replace(
            cut_from_words(words, first, last, s),
            method="claude",
            score=decision.cut.score,
            doubt=decision.cut.doubt,
        )
        return cut, advice


def _bounds_prompt(
    words: list[Word],
    reference: str,
    decision: Decision,
    noted_start: float,
    noted_end: float,
    s: Settings,
) -> str:
    lines = [
        f"Noted start: {format_tc(noted_start)} (±{s.tolerance_s:g} s)",
        f"Noted end: {format_tc(noted_end)} (±{s.tolerance_s:g} s)",
        f"Noted line: {reference}",
        "",
        "Fragments found in the transcript:",
    ]
    for m in decision.matches:
        if m is not None:
            lines.append(f'- "{m.fragment}": words {m.first} to {m.last} (score {m.score:.0f})')
    if all(m is None for m in decision.matches):
        lines.append("- none")
    if decision.first_word is not None and decision.last_word is not None:
        lines.append(
            f"\nProposal without you: words {decision.first_word} to {decision.last_word}."
        )
    lines.append("\nTranscript ([index] start-end word):")
    lines.extend(f"[{i}] {w.start:.2f}-{w.end:.2f} {w.text}" for i, w in enumerate(words))
    return "\n".join(lines)
