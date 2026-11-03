"""
LLM-powered column transformations (the optional "creative" requirement).

Two transformations share one engine:

* **Standardize** - rewrite a column in place following an instruction, e.g.
  "convert dates to YYYY-MM-DD", "title-case the names", "use ISO country codes".
  These are fuzzy normalisations that a single regex cannot express.
* **Derive** - create a new column computed from an existing one, e.g.
  "classify the review as positive, neutral or negative", "extract the company
  name from the email domain", "translate to English".

How it works: the column's *distinct* non-empty values are sent to the LLM in
small batches as ``[{"id": 0, "value": "..."}, ...]`` and the model returns
``{"results": [{"id": 0, "value": "..."}]}``. Ids (not the values themselves)
are used as keys so that whitespace or Unicode normalisation by the model can't
break the mapping. Missing ids are retried once; anything still missing keeps
its original value (standardize) or stays empty (derive) and is reported.

Working on distinct values keeps cost proportional to the column's cardinality
rather than to the row count, which is what makes this usable on large files.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field

import pandas as pd

from processor.exceptions import ColumnError, LLMError, ProcessingError
from processor.services.llm import LLMClient, parse_json_object

logger = logging.getLogger(__name__)

STANDARDIZE = "standardize"
DERIVE = "derive"

SYSTEM_PROMPT = """\
You transform spreadsheet cell values according to a user's instruction.

You receive a JSON array of {"id": <int>, "value": <string>} items. Apply the \
instruction to each value independently and reply with ONLY a JSON object:

{"results": [{"id": <int>, "value": <string>}, ...]}

Rules:
- Return exactly one result for every input id. Never skip or invent ids.
- Output values are plain strings. Do not add commentary, quotes or units the \
instruction did not ask for.
- If the instruction does not apply to a value, or you cannot determine an \
answer, return the input value unchanged for a cleanup task, or an empty \
string for a classification/extraction task.
- Be consistent: equivalent inputs must produce identical outputs.
"""


@dataclass
class TransformResult:
    frame: pd.DataFrame
    target_column: str
    distinct_values: int = 0
    cells_changed: int = 0
    unresolved: int = 0
    samples: list[dict] = field(default_factory=list)

    def stats(self) -> dict:
        return {
            "distinct_values": self.distinct_values,
            "cells_changed": self.cells_changed,
            "unresolved": self.unresolved,
            "per_column": {self.target_column: {"cells_changed": self.cells_changed}},
        }


class ColumnTransformer:
    def __init__(self, llm: LLMClient, *, batch_size: int = 40, max_unique_values: int = 500) -> None:
        self.llm = llm
        self.batch_size = batch_size
        self.max_unique_values = max_unique_values

    def apply(
        self,
        frame: pd.DataFrame,
        *,
        kind: str,
        column: str,
        instruction: str,
        new_column: str | None = None,
        sample_limit: int = 6,
    ) -> TransformResult:
        if column not in frame.columns:
            raise ColumnError(f"Column '{column}' does not exist.")
        target = column
        if kind == DERIVE:
            target = (new_column or "").strip()
            if not target:
                raise ColumnError("Give the new column a name.")
            if target in frame.columns:
                raise ColumnError(f"A column named '{target}' already exists.")
        elif kind != STANDARDIZE:
            raise ProcessingError(f"Unknown transformation '{kind}'.")

        series = frame[column]
        distinct = [value for value in series.drop_duplicates().tolist() if value.strip()]
        if not distinct:
            raise ColumnError(f"Column '{column}' has no values to transform.")
        if len(distinct) > self.max_unique_values:
            raise ProcessingError(
                f"Column '{column}' has {len(distinct):,} distinct values; LLM transformations are "
                f"limited to {self.max_unique_values:,}. Use find & replace for high-cardinality columns."
            )

        mapping = self._transform_values(instruction, distinct, cleanup=(kind == STANDARDIZE))
        unresolved = len(distinct) - len(mapping)

        result_frame = frame.copy()
        if kind == STANDARDIZE:
            new_series = series.map(lambda value: mapping.get(value, value))
            result_frame[column] = new_series
        else:
            new_series = series.map(lambda value: mapping.get(value, ""))
            insert_at = result_frame.columns.get_loc(column) + 1
            result_frame.insert(insert_at, target, new_series)

        changed_mask = new_series != series
        result = TransformResult(
            frame=result_frame,
            target_column=target,
            distinct_values=len(distinct),
            cells_changed=int(changed_mask.sum()),
            unresolved=unresolved,
        )
        for before in series[changed_mask].drop_duplicates().head(sample_limit):
            result.samples.append({"before": before, "after": mapping.get(before, "")})
        return result

    # ------------------------------------------------------------------ helpers

    def _transform_values(self, instruction: str, values: list[str], *, cleanup: bool) -> dict[str, str]:
        mapping: dict[str, str] = {}
        task = "cleanup" if cleanup else "classification/extraction"
        for start in range(0, len(values), self.batch_size):
            batch = values[start : start + self.batch_size]
            pending = dict(enumerate(batch))
            for _ in range(2):  # one retry for ids the model skipped
                if not pending:
                    break
                answered = self._call(instruction, task, pending)
                for item_id, output in answered.items():
                    mapping[pending.pop(item_id)] = output
            if pending:
                logger.warning("LLM left %s values unresolved", len(pending))
        return mapping

    def _call(self, instruction: str, task: str, items: dict[int, str]) -> dict[int, str]:
        payload = json.dumps([{"id": i, "value": v} for i, v in items.items()], ensure_ascii=False)
        prompt = (
            f"Instruction ({task} task): {instruction.strip()}\n\n"
            f"Values:\n{payload}\n\nReply with the JSON object only."
        )
        reply = self.llm.complete(SYSTEM_PROMPT, [{"role": "user", "content": prompt}], max_tokens=4096)
        data = parse_json_object(reply)
        results = data.get("results")
        if not isinstance(results, list):
            raise LLMError('The language model reply is missing the "results" list.')

        answered: dict[int, str] = {}
        for entry in results:
            if not isinstance(entry, dict):
                continue
            try:
                item_id = int(entry.get("id"))
            except (TypeError, ValueError):
                continue
            value = entry.get("value")
            if item_id in items and value is not None:
                answered[item_id] = value if isinstance(value, str) else str(value)
        return answered
