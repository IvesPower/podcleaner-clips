"""Claude's opinion on the abbreviation and the clip bounds, always with a fallback.

Without an API key, with Claude turned off, on an API error or on an answer that does not
pass the checks, the result is the one computed without Claude.
"""

import json
import os
import re
from dataclasses import dataclass, replace
from typing import Any

import anthropic

from podcleaner_clips.adjust import Cut, Decision, Word, bounds_ok, cut_from_words
from podcleaner_clips.config import Settings
from podcleaner_clips.naming import fallback_abbreviation, format_tc

_ABBREVIATION = re.compile(r"^[A-Z0-9]{2,6}$")
_MAX_TOKENS = 16000

_ABBREVIATION_SCHEMA = {
    "type": "object",
    "properties": {"abreviation": {"type": "string"}, "raison": {"type": "string"}},
    "required": ["abreviation", "raison"],
    "additionalProperties": False,
}
_BOUNDS_SCHEMA = {
    "type": "object",
    "properties": {
        "premier_mot": {"type": "integer"},
        "dernier_mot": {"type": "integer"},
        "raison": {"type": "string"},
    },
    "required": ["premier_mot", "dernier_mot", "raison"],
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
    kind: str  # "abreviation" or "bornes"
    answer: str
    reason: str
    model: str


class ClaudeClient:
    """Asks Claude when it is available; `warnings` collects the errors met on the way."""

    def __init__(self, s: Settings, client: Any = None) -> None:
        self.model = s.claude_model
        self.warnings: list[str] = []
        if not s.claude_enabled:
            client = None
        elif client is None and os.environ.get("ANTHROPIC_API_KEY"):
            client = anthropic.Anthropic()
        self._client = client

    @property
    def available(self) -> bool:
        return self._client is not None

    def _ask(self, system: str, prompt: str, schema: dict) -> dict | None:
        """Claude's JSON answer, or None (with a warning) if there is none to use."""
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
        abbr = data.get("abreviation")
        if not isinstance(abbr, str) or not _ABBREVIATION.match(abbr):
            return fallback, None
        return abbr, ClaudeAdvice("abreviation", abbr, str(data.get("raison", "")), self.model)

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
        first, last = data.get("premier_mot"), data.get("dernier_mot")
        if not isinstance(first, int) or not isinstance(last, int):
            return decision.cut, None
        advice = ClaudeAdvice("bornes", f"{first}-{last}", str(data.get("raison", "")), self.model)
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
