"""
Regex compilation, validation and DataFrame replacement.

This module is framework-free (no Django imports) so it can be unit tested and
reused on its own.

Design notes
------------
* The third-party ``regex`` package is used instead of ``re`` because it
  supports a per-call ``timeout``. Patterns come from an LLM (or a user), so a
  catastrophically backtracking pattern must not be able to hang a worker.
* Replacement runs once per *unique* cell value and the result is mapped back
  onto the column. Real-world text columns repeat values a lot (statuses,
  domains, names), so this is usually far faster than a per-row loop while
  still letting every call be time-boxed.
* By default the replacement value is inserted literally. Group references
  (``\\1``, ``\\g<name>``) are only interpreted when explicitly enabled, so a
  replacement such as ``C:\\new`` cannot be misread as a template.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Iterable, Sequence

import pandas as pd
import regex

from processor.exceptions import OperationTimeout, PatternError

SUPPORTED_FLAGS: dict[str, int] = {
    "IGNORECASE": regex.IGNORECASE,
    "MULTILINE": regex.MULTILINE,
    "DOTALL": regex.DOTALL,
}
MAX_PATTERN_LENGTH = 2000


def compile_pattern(pattern: str, flags: Iterable[str] = ()) -> regex.Pattern:
    """Compile and sanity-check a pattern, raising :class:`PatternError`."""
    if not pattern or not pattern.strip():
        raise PatternError("The regex pattern is empty.")
    if len(pattern) > MAX_PATTERN_LENGTH:
        raise PatternError(f"The regex pattern is longer than {MAX_PATTERN_LENGTH} characters.")

    flag_value = 0
    for name in flags:
        try:
            flag_value |= SUPPORTED_FLAGS[name.upper()]
        except KeyError as exc:
            supported = ", ".join(SUPPORTED_FLAGS)
            raise PatternError(f"Unsupported regex flag '{name}'. Supported: {supported}.") from exc

    try:
        compiled = regex.compile(pattern, flag_value)
    except (regex.error, OverflowError, RecursionError) as exc:
        raise PatternError(f"Invalid regex: {exc}") from exc

    if compiled.fullmatch("") is not None:
        raise PatternError(
            "The pattern matches empty text, which would insert the replacement between "
            "every character. Make it match at least one character."
        )
    return compiled


def check_zero_width_matches(compiled: regex.Pattern, values: Iterable[str], timeout: float) -> None:
    """Reject patterns that produce zero-width matches (e.g. ``\\b`` or ``(?=x)``)."""
    for value in values:
        try:
            for match in compiled.finditer(value, timeout=timeout):
                if match.start() == match.end():
                    raise PatternError(
                        "The pattern produces empty matches (for example at word boundaries). "
                        "It must consume at least one character."
                    )
        except TimeoutError as exc:
            raise OperationTimeout(_timeout_message(timeout)) from exc


@dataclass
class CellChange:
    row: int
    column: str
    before: str
    after: str


@dataclass
class ReplaceResult:
    frame: pd.DataFrame
    cells_changed: int = 0
    matches: int = 0
    per_column: dict[str, dict[str, int]] = field(default_factory=dict)
    samples: list[CellChange] = field(default_factory=list)

    def stats(self) -> dict:
        return {
            "cells_changed": self.cells_changed,
            "matches": self.matches,
            "per_column": self.per_column,
        }


def replace_in_frame(
    frame: pd.DataFrame,
    compiled: regex.Pattern,
    replacement: str,
    columns: Sequence[str],
    *,
    use_backrefs: bool = False,
    cell_timeout: float = 0.5,
    time_budget: float = 90.0,
    sample_limit: int = 0,
) -> ReplaceResult:
    """Apply ``compiled`` to ``columns`` of ``frame`` and return a new frame.

    The input frame is never mutated. ``sample_limit`` collects up to N
    before/after examples (used by the preview endpoint).
    """
    deadline = time.monotonic() + time_budget
    replace_fn = _build_replacer(compiled, replacement, use_backrefs)
    result_frame = frame.copy()
    result = ReplaceResult(frame=result_frame)

    for column in columns:
        series = frame[column]
        counts = series.value_counts(sort=False)
        mapping: dict[str, str] = {}
        column_matches = 0

        for value, occurrences in counts.items():
            if time.monotonic() > deadline:
                raise OperationTimeout(
                    f"The replacement did not finish within {time_budget:.0f} seconds. "
                    "Try a simpler pattern or fewer columns."
                )
            text = value if isinstance(value, str) else str(value)
            if not text:
                continue
            try:
                new_text, n = replace_fn(text, cell_timeout)
            except TimeoutError as exc:
                raise OperationTimeout(_timeout_message(cell_timeout)) from exc
            if n:
                column_matches += n * int(occurrences)
                if new_text != text:
                    mapping[text] = new_text

        changed_mask = series.isin(list(mapping)) if mapping else pd.Series(False, index=series.index)
        changed_count = int(changed_mask.sum())
        if changed_count:
            result_frame.loc[changed_mask, column] = series[changed_mask].map(mapping)

        result.per_column[column] = {"matches": column_matches, "cells_changed": changed_count}
        result.matches += column_matches
        result.cells_changed += changed_count

        if sample_limit and changed_count and len(result.samples) < sample_limit:
            remaining = sample_limit - len(result.samples)
            for position in changed_mask.to_numpy().nonzero()[0][:remaining]:
                before = series.iat[position]
                result.samples.append(
                    CellChange(row=int(position), column=column, before=before, after=mapping[before])
                )

    return result


def _build_replacer(compiled: regex.Pattern, replacement: str, use_backrefs: bool):
    if use_backrefs:
        # Validate the template up front so a bad group reference fails fast.
        try:
            compiled.subn(replacement, "", timeout=1)
        except (regex.error, IndexError) as exc:
            raise PatternError(f"Invalid group reference in replacement: {exc}") from exc

        def replace(text: str, timeout: float) -> tuple[str, int]:
            try:
                return compiled.subn(replacement, text, timeout=timeout)
            except (regex.error, IndexError) as exc:
                raise PatternError(f"Invalid group reference in replacement: {exc}") from exc

        return replace

    def literal(_match: regex.Match) -> str:
        return replacement

    def replace_literal(text: str, timeout: float) -> tuple[str, int]:
        return compiled.subn(literal, text, timeout=timeout)

    return replace_literal


def _timeout_message(timeout: float) -> str:
    return (
        f"The pattern took longer than {timeout:g}s on a single cell, which usually means "
        "catastrophic backtracking. Simplify nested quantifiers such as (a+)+."
    )
