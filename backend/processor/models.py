"""
Data model.

A :class:`Dataset` is one uploaded file. Each change applied to it is an
:class:`Operation` that records *what* was asked (natural language, regex,
replacement, columns) and points at an immutable snapshot of the resulting
table. The current state of a dataset is simply the snapshot of its latest
operation (or the base snapshot when there are none), which makes undo and
"reset to original" trivial and gives users an audit trail of their edits.
"""
from __future__ import annotations

import uuid
from pathlib import PurePosixPath

from django.db import models


def upload_path(instance: "Dataset", filename: str) -> str:
    return f"datasets/{instance.id}/original{PurePosixPath(filename).suffix.lower()}"


class Dataset(models.Model):
    class FileType(models.TextChoices):
        CSV = "csv", "CSV"
        XLSX = "xlsx", "Excel (.xlsx)"
        XLS = "xls", "Excel 97-2003 (.xls)"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=255)
    file_type = models.CharField(max_length=8, choices=FileType.choices)
    size_bytes = models.PositiveBigIntegerField(default=0)
    original_file = models.FileField(upload_to=upload_path, max_length=500)
    base_snapshot = models.CharField(max_length=500, blank=True)
    base_columns = models.JSONField(default=list, blank=True)
    row_count = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.name} ({self.row_count} rows)"

    @property
    def latest_operation(self) -> "Operation | None":
        return self.operations.order_by("-sequence").first()

    @property
    def current_snapshot(self) -> str:
        latest = self.latest_operation
        return latest.snapshot if latest else self.base_snapshot

    @property
    def current_columns(self) -> list[dict]:
        latest = self.latest_operation
        return latest.columns_after if latest else self.base_columns


class Operation(models.Model):
    class Kind(models.TextChoices):
        REGEX_REPLACE = "regex_replace", "Find & replace"
        STANDARDIZE = "standardize", "Standardize values"
        DERIVE = "derive", "Derive new column"

    dataset = models.ForeignKey(Dataset, on_delete=models.CASCADE, related_name="operations")
    sequence = models.PositiveIntegerField()
    kind = models.CharField(max_length=20, choices=Kind.choices)
    instruction = models.TextField(blank=True)
    pattern = models.TextField(blank=True)
    flags = models.JSONField(default=list, blank=True)
    replacement = models.TextField(blank=True)
    use_backrefs = models.BooleanField(default=False)
    columns = models.JSONField(default=list, blank=True)
    explanation = models.TextField(blank=True)
    stats = models.JSONField(default=dict, blank=True)
    snapshot = models.CharField(max_length=500)
    columns_after = models.JSONField(default=list, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["sequence"]
        constraints = [
            models.UniqueConstraint(fields=["dataset", "sequence"], name="unique_operation_sequence"),
        ]

    def __str__(self) -> str:
        return f"#{self.sequence} {self.get_kind_display()} on {self.dataset_id}"
