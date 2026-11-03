"""
Natural language -> regex, using an LLM.

Accuracy strategy
-----------------
1. **Context.** The prompt lists the dataset's columns, their inferred kind and
   (optionally) a few sample values, so "find the order numbers" can be
   grounded in what the data actually looks like.
2. **Structured output.** The model must answer with a small JSON object
   (pattern, flags, target columns, replacement, explanation). Column names and
   a replacement mentioned inside the sentence are extracted as well, so
   "replace emails in the Email column with REDACTED" works in one go.
3. **Validate, then self-correct.** Every answer is parsed, compiled and
   checked (no empty matches, columns must exist). If anything fails, the
   error is sent back to the model and it gets another attempt.
4. **Grounding check.** If a valid pattern matches *none* of the sample values
   of its target columns, the model is asked once to double-check. Its second
   answer is accepted either way, because "no matches" can be legitimate.
"""
from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from typing import Any, Sequence

from processor.exceptions import LLMError, PatternError, ProcessingError
from processor.services.llm import LLMClient, Message, parse_json_object
from processor.services.regex_engine import SUPPORTED_FLAGS, check_zero_width_matches, compile_pattern

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """\
You translate natural-language descriptions of text patterns into regular \
expressions for Python's `regex` module (a superset of the standard `re` syntax).

You are given an instruction written by a user working with a spreadsheet, plus \
the spreadsheet's columns with example values. Reply with ONLY a JSON object, \
no prose and no Markdown, with exactly these keys:

{
  "pattern": "<the regex>",
  "flags": ["IGNORECASE" | "MULTILINE" | "DOTALL", ...],
  "columns": ["<exact column names the instruction refers to>"],
  "replacement": "<replacement text if the instruction states one, otherwise null>",
  "explanation": "<one short sentence describing what the pattern matches>"
}

Rules for the pattern:
- Match only the thing described, not the whole cell, unless the user asks for \
whole cells (then anchor it with ^ and $).
- Prefer precise, widely used patterns (e.g. for emails, URLs, phone numbers, \
dates, postcodes, IP addresses, credit card numbers).
- Use \\b word boundaries where they help avoid partial-word matches.
- The pattern must consume at least one character; it must never match empty text.
- Avoid nested quantifiers that can backtrack catastrophically, such as (a+)+.
- Use IGNORECASE instead of spelling out both cases when case does not matter.
- Remember that backslashes must be escaped inside JSON strings ("\\\\d" for \\d).

Rules for the other keys:
- "columns": copy names exactly from the provided list. Use [] when the \
instruction does not mention specific columns.
- "replacement": only when the instruction clearly says what to replace matches \
with (e.g. "replace them with 'REDACTED'" -> "REDACTED"). Use null otherwise. \
You may use \\1 or \\g<name> group references only if the user asks to keep \
or rearrange parts of the match.

Examples:
Instruction: Find email addresses in the Email column and replace them with 'REDACTED'.
{"pattern": "\\\\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\\\\.[A-Za-z]{2,}\\\\b", "flags": [], \
"columns": ["Email"], "replacement": "REDACTED", "explanation": "Email addresses."}

Instruction: phone numbers like (555) 123-4567 or 555-123-4567
{"pattern": "(?:\\\\(\\\\d{3}\\\\)\\\\s?|\\\\b\\\\d{3}[-.\\\\s])\\\\d{3}[-.\\\\s]\\\\d{4}\\\\b", \
"flags": [], "columns": [], "replacement": null, \
"explanation": "North American phone numbers with or without parentheses."}

Instruction: the word "inc" or "incorporated" at the end of company names
{"pattern": ",?\\\\s+(?:inc\\\\.?|incorporated)$", "flags": ["IGNORECASE"], "columns": [], \
"replacement": null, "explanation": "A trailing 'Inc', 'Inc.' or 'Incorporated' suffix."}
"""


@dataclass
class ColumnContext:
    name: str
    kind: str
    samples: list[str] = field(default_factory=list)


@dataclass
class RegexSuggestion:
    pattern: str
    flags: list[str]
    columns: list[str]
    replacement: str | None
    explanation: str
    attempts: int

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


class RegexGenerator:
    def __init__(self, llm: LLMClient, *, max_attempts: int = 3, cell_timeout: float = 0.5) -> None:
        self.llm = llm
        self.max_attempts = max_attempts
        self.cell_timeout = cell_timeout

    def generate(
        self,
        instruction: str,
        columns: Sequence[ColumnContext],
        *,
        target_columns: Sequence[str] = (),
    ) -> RegexSuggestion:
        """Turn ``instruction`` into a validated :class:`RegexSuggestion`.

        ``target_columns`` are columns the user already picked in the UI; they
        are passed as a hint and take precedence over columns the model infers.
        """
        messages: list[Message] = [
            {"role": "user", "content": self._build_prompt(instruction, columns, target_columns)}
        ]
        by_name = {column.name: column for column in columns}
        grounding_checked = False
        last_error: ProcessingError | None = None
        fallback: RegexSuggestion | None = None  # valid answer awaiting a grounding re-check

        for attempt in range(1, self.max_attempts + 1):
            reply = self.llm.complete(SYSTEM_PROMPT, messages, max_tokens=800)
            messages.append({"role": "assistant", "content": reply})
            try:
                suggestion = self._parse(reply, by_name, attempt)
            except (PatternError, LLMError) as error:
                last_error = error
                logger.info("Regex attempt %s rejected: %s", attempt, error.message)
                messages.append({"role": "user", "content": _correction_prompt(error.message)})
                continue

            if target_columns:
                suggestion.columns = list(target_columns)

            if not grounding_checked and attempt < self.max_attempts:
                grounding_checked = True
                feedback = self._grounding_feedback(suggestion, by_name)
                if feedback:
                    fallback = suggestion
                    messages.append({"role": "user", "content": feedback})
                    continue
            return suggestion

        if fallback is not None:
            return fallback
        raise PatternError(
            "The language model could not produce a valid regex for that description. "
            "Try rephrasing it more specifically.",
            details=last_error.message if last_error else None,
        )

    # ------------------------------------------------------------------ helpers

    def _build_prompt(
        self, instruction: str, columns: Sequence[ColumnContext], target_columns: Sequence[str]
    ) -> str:
        lines = [f"Instruction: {instruction.strip()}", "", "Columns:"]
        for column in columns:
            samples = ", ".join(json.dumps(value, ensure_ascii=False) for value in column.samples)
            lines.append(f"- {json.dumps(column.name)} ({column.kind})" + (f": {samples}" if samples else ""))
        if target_columns:
            lines += ["", "The user has already selected these columns: " + ", ".join(target_columns)]
        lines += ["", "Reply with the JSON object only."]
        return "\n".join(lines)

    def _parse(self, reply: str, by_name: dict[str, ColumnContext], attempt: int) -> RegexSuggestion:
        data = parse_json_object(reply)

        pattern = data.get("pattern")
        if not isinstance(pattern, str) or not pattern:
            raise LLMError('The JSON must contain a non-empty string "pattern".')

        flags = data.get("flags") or []
        if not isinstance(flags, list) or not all(isinstance(flag, str) for flag in flags):
            raise LLMError('"flags" must be a list of strings.')
        flags = sorted({flag.upper() for flag in flags})
        unknown = [flag for flag in flags if flag not in SUPPORTED_FLAGS]
        if unknown:
            raise PatternError(f"Unsupported flags {unknown}. Use only {list(SUPPORTED_FLAGS)}.")

        compiled = compile_pattern(pattern, flags)
        all_samples = [value for column in by_name.values() for value in column.samples]
        check_zero_width_matches(compiled, all_samples, self.cell_timeout)

        columns = _resolve_columns(data.get("columns") or [], by_name)

        replacement = data.get("replacement")
        if replacement is not None and not isinstance(replacement, str):
            replacement = str(replacement)

        explanation = data.get("explanation")
        return RegexSuggestion(
            pattern=pattern,
            flags=flags,
            columns=columns,
            replacement=replacement,
            explanation=explanation if isinstance(explanation, str) else "",
            attempts=attempt,
        )

    def _grounding_feedback(self, suggestion: RegexSuggestion, by_name: dict[str, ColumnContext]) -> str | None:
        targets = suggestion.columns or [name for name, column in by_name.items() if column.kind == "text"]
        samples = [value for name in targets if name in by_name for value in by_name[name].samples]
        if not samples:
            return None
        compiled = compile_pattern(suggestion.pattern, suggestion.flags)
        try:
            if any(compiled.search(value, timeout=self.cell_timeout) for value in samples):
                return None
        except TimeoutError:
            return _correction_prompt("The pattern timed out on a sample value (catastrophic backtracking).")
        return (
            "Your pattern matches none of the sample values shown for the target columns. "
            "If the instruction implies that such values exist, revise the pattern to fit the "
            "data's actual format. If no match is genuinely expected, return the same JSON again."
        )


def _resolve_columns(raw: Any, by_name: dict[str, ColumnContext]) -> list[str]:
    """Map model-provided column names onto real ones (case-insensitively)."""
    if not isinstance(raw, list):
        raise LLMError('"columns" must be a list of column names.')
    lookup = {name.casefold(): name for name in by_name}
    resolved: list[str] = []
    for item in raw:
        name = lookup.get(str(item).strip().casefold())
        if name is None:
            raise LLMError(f"Column {item!r} does not exist. Choose from: {list(by_name)}.")
        if name not in resolved:
            resolved.append(name)
    return resolved


def _correction_prompt(error: str) -> str:
    return f"That answer was rejected: {error} Fix it and reply with the corrected JSON object only."
