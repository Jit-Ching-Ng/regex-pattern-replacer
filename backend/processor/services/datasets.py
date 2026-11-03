"""
Application service: the use cases behind the API.

Views stay thin (parse input -> call one method here -> serialise output) and
the pure building blocks (``file_io``, ``regex_engine``, ``regex_generation``,
``transforms``) stay free of Django. This class is where they meet the
database and the snapshot store.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Sequence

import pandas as pd
from django.conf import settings
from django.core.files.uploadedfile import UploadedFile
from django.db import transaction

from processor.exceptions import ColumnError, FileValidationError, NothingToUndo
from processor.models import Dataset, Operation
from processor.services import file_io
from processor.services.llm import LLMClient, get_llm_client
from processor.services.regex_engine import check_zero_width_matches, compile_pattern, replace_in_frame
from processor.services.regex_generation import ColumnContext, RegexGenerator, RegexSuggestion
from processor.services.storage import SnapshotStore, get_store
from processor.services.transforms import DERIVE, STANDARDIZE, ColumnTransformer

logger = logging.getLogger(__name__)

PREVIEW_SAMPLE_LIMIT = 8


@dataclass
class RegexSpec:
    """A fully specified find & replace request."""

    pattern: str
    flags: list[str]
    replacement: str
    columns: list[str]
    use_backrefs: bool = False
    instruction: str = ""
    explanation: str = ""


class DatasetService:
    def __init__(
        self,
        store: SnapshotStore | None = None,
        llm_factory: Callable[[], LLMClient] | None = None,
    ) -> None:
        self.store = store or get_store()
        self.llm_factory = llm_factory or get_llm_client

    # ------------------------------------------------------------------ upload

    def create(self, uploaded: UploadedFile) -> Dataset:
        file_type = file_io.detect_file_type(uploaded.name)
        limit = settings.MAX_UPLOAD_SIZE_MB * 1024 * 1024
        if uploaded.size > limit:
            raise FileValidationError(f"The file is larger than the {settings.MAX_UPLOAD_SIZE_MB} MB limit.")
        if uploaded.size == 0:
            raise FileValidationError("The file is empty.")

        dataset = Dataset(name=Path(uploaded.name).name[:255], file_type=file_type, size_bytes=uploaded.size)
        dataset.original_file.save(uploaded.name, uploaded, save=False)
        try:
            frame = file_io.read_table(
                Path(dataset.original_file.path), file_type, max_rows=settings.MAX_ROWS
            )
            dataset.row_count = len(frame)
            dataset.base_columns = [column.as_dict() for column in file_io.profile_columns(frame)]
            dataset.base_snapshot = self.store.write(dataset.id, frame, "base")
            dataset.save()
        except Exception:
            self.store.delete_dataset(dataset.id)
            raise
        logger.info("Created dataset %s (%s rows)", dataset.id, dataset.row_count)
        return dataset

    def delete(self, dataset: Dataset) -> None:
        dataset_id = dataset.id
        dataset.delete()
        self.store.delete_dataset(dataset_id)

    # ------------------------------------------------------------------ reading

    def current_frame(self, dataset: Dataset) -> pd.DataFrame:
        return self.store.read(dataset.current_snapshot)

    def rows(self, dataset: Dataset, *, page: int, page_size: int, highlight: bool) -> dict:
        frame = self.current_frame(dataset)
        total = len(frame)
        start = (page - 1) * page_size
        window = frame.iloc[start : start + page_size]

        changed: list[list[int]] = []
        operations = list(dataset.operations.order_by("-sequence")[:2])
        if highlight and operations and not window.empty:
            previous_path = operations[1].snapshot if len(operations) > 1 else dataset.base_snapshot
            previous = self.store.read(previous_path).iloc[start : start + page_size]
            changed = _changed_cells(window, previous)

        return {
            "page": page,
            "page_size": page_size,
            "total_rows": total,
            "total_pages": max(1, -(-total // page_size)),
            "offset": start,
            "columns": dataset.current_columns,
            "rows": window.to_numpy().tolist(),
            "changed": changed,
        }

    def export(self, dataset: Dataset, file_format: str) -> tuple[bytes, str, str]:
        payload, content_type = file_io.export_bytes(self.current_frame(dataset), file_format)
        filename = f"{Path(dataset.name).stem}_processed.{file_format}"
        return payload, content_type, filename

    # ------------------------------------------------------------------ regex

    def suggest_regex(
        self, dataset: Dataset, instruction: str, *, target_columns: Sequence[str] = ()
    ) -> RegexSuggestion:
        frame = self.current_frame(dataset)
        self._validate_columns(dataset, target_columns)
        send_samples = settings.LLM_SEND_SAMPLE_VALUES
        context = [
            ColumnContext(
                name=column["name"],
                kind=column["kind"],
                samples=file_io.sample_values(frame, column["name"]) if send_samples else [],
            )
            for column in dataset.current_columns
        ]
        generator = RegexGenerator(self.llm_factory(), cell_timeout=settings.REGEX_CELL_TIMEOUT_SECONDS)
        return generator.generate(instruction, context, target_columns=target_columns)

    def preview_regex(self, dataset: Dataset, spec: RegexSpec) -> dict:
        columns = self._target_columns(dataset, spec.columns)
        frame = self.current_frame(dataset)
        result = replace_in_frame(
            frame,
            self._compile(frame, spec, columns),
            spec.replacement,
            columns,
            use_backrefs=spec.use_backrefs,
            cell_timeout=settings.REGEX_CELL_TIMEOUT_SECONDS,
            time_budget=settings.OPERATION_TIME_BUDGET_SECONDS,
            sample_limit=PREVIEW_SAMPLE_LIMIT,
        )
        return {
            **result.stats(),
            "columns": columns,
            "samples": [sample.__dict__ for sample in result.samples],
        }

    def apply_regex(self, dataset: Dataset, spec: RegexSpec) -> Operation:
        columns = self._target_columns(dataset, spec.columns)
        frame = self.current_frame(dataset)
        result = replace_in_frame(
            frame,
            self._compile(frame, spec, columns),
            spec.replacement,
            columns,
            use_backrefs=spec.use_backrefs,
            cell_timeout=settings.REGEX_CELL_TIMEOUT_SECONDS,
            time_budget=settings.OPERATION_TIME_BUDGET_SECONDS,
        )
        return self._commit(
            dataset,
            result.frame,
            kind=Operation.Kind.REGEX_REPLACE,
            instruction=spec.instruction,
            pattern=spec.pattern,
            flags=spec.flags,
            replacement=spec.replacement,
            use_backrefs=spec.use_backrefs,
            columns=columns,
            explanation=spec.explanation,
            stats=result.stats(),
        )

    # ------------------------------------------------------------------ LLM transforms

    def apply_transform(
        self, dataset: Dataset, *, kind: str, column: str, instruction: str, new_column: str | None
    ) -> tuple[Operation, list[dict]]:
        self._validate_columns(dataset, [column])
        transformer = ColumnTransformer(
            self.llm_factory(),
            batch_size=settings.TRANSFORM_BATCH_SIZE,
            max_unique_values=settings.TRANSFORM_MAX_UNIQUE_VALUES,
        )
        result = transformer.apply(
            self.current_frame(dataset), kind=kind, column=column, instruction=instruction, new_column=new_column
        )
        operation_kind = Operation.Kind.STANDARDIZE if kind == STANDARDIZE else Operation.Kind.DERIVE
        operation = self._commit(
            dataset,
            result.frame,
            kind=operation_kind,
            instruction=instruction,
            columns=[column] + ([result.target_column] if kind == DERIVE else []),
            stats=result.stats(),
        )
        return operation, result.samples

    # ------------------------------------------------------------------ history

    @transaction.atomic
    def undo(self, dataset: Dataset) -> dict:
        """Drop the latest operation and return a short description of it."""
        latest = Dataset.objects.select_for_update().get(pk=dataset.pk).latest_operation
        if latest is None:
            raise NothingToUndo("There is nothing to undo.")
        undone = {"sequence": latest.sequence, "kind": latest.kind, "instruction": latest.instruction}
        snapshot = latest.snapshot
        latest.delete()
        transaction.on_commit(lambda: self.store.delete(snapshot))
        return undone

    @transaction.atomic
    def reset(self, dataset: Dataset) -> int:
        """Drop every operation, returning the dataset to its uploaded state."""
        locked = Dataset.objects.select_for_update().get(pk=dataset.pk)
        snapshots = list(locked.operations.values_list("snapshot", flat=True))
        locked.operations.all().delete()
        transaction.on_commit(lambda: self._delete_snapshots(snapshots))
        return len(snapshots)

    def _delete_snapshots(self, paths: Sequence[str]) -> None:
        for path in paths:
            self.store.delete(path)

    # ------------------------------------------------------------------ helpers

    def _commit(self, dataset: Dataset, frame: pd.DataFrame, *, kind: str, **fields) -> Operation:
        snapshot = self.store.write(dataset.id, frame, kind)
        columns_after = [column.as_dict() for column in file_io.profile_columns(frame)]
        try:
            with transaction.atomic():
                locked = Dataset.objects.select_for_update().get(pk=dataset.pk)
                latest = locked.latest_operation
                operation = Operation.objects.create(
                    dataset=locked,
                    sequence=(latest.sequence + 1) if latest else 1,
                    kind=kind,
                    snapshot=snapshot,
                    columns_after=columns_after,
                    **fields,
                )
                locked.save(update_fields=["updated_at"])
        except Exception:
            self.store.delete(snapshot)
            raise
        return operation

    def _compile(self, frame: pd.DataFrame, spec: RegexSpec, columns: Sequence[str]):
        """Compile the pattern and reject zero-width matches on a sample of the data."""
        compiled = compile_pattern(spec.pattern, spec.flags)
        samples = [value for column in columns for value in file_io.sample_values(frame, column, limit=50)]
        check_zero_width_matches(compiled, samples, settings.REGEX_CELL_TIMEOUT_SECONDS)
        return compiled

    def _validate_columns(self, dataset: Dataset, columns: Sequence[str]) -> None:
        known = {column["name"] for column in dataset.current_columns}
        missing = [column for column in columns if column not in known]
        if missing:
            raise ColumnError(f"Unknown column(s): {', '.join(missing)}.", details={"available": sorted(known)})

    def _target_columns(self, dataset: Dataset, requested: Sequence[str]) -> list[str]:
        """Explicit columns if given, otherwise every text column."""
        if requested:
            self._validate_columns(dataset, requested)
            return list(dict.fromkeys(requested))
        text_columns = [column["name"] for column in dataset.current_columns if column["kind"] == "text"]
        if not text_columns:
            raise ColumnError("The dataset has no text columns. Pick the columns to search explicitly.")
        return text_columns


def _changed_cells(current: pd.DataFrame, previous: pd.DataFrame) -> list[list[int]]:
    """Cells that differ between two equally-sized windows, as [row, column] pairs."""
    changed: list[list[int]] = []
    for column_index, column in enumerate(current.columns):
        values = current[column].to_numpy()
        if column in previous.columns:
            mask = values != previous[column].to_numpy()
        else:  # a column created by the last operation
            mask = values != ""
        changed.extend([int(row), column_index] for row in mask.nonzero()[0])
    return changed
