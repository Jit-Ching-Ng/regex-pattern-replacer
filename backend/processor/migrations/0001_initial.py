import uuid

import django.db.models.deletion
from django.db import migrations, models

import processor.models


class Migration(migrations.Migration):

    initial = True

    dependencies = []

    operations = [
        migrations.CreateModel(
            name="Dataset",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("name", models.CharField(max_length=255)),
                (
                    "file_type",
                    models.CharField(
                        choices=[("csv", "CSV"), ("xlsx", "Excel (.xlsx)"), ("xls", "Excel 97-2003 (.xls)")],
                        max_length=8,
                    ),
                ),
                ("size_bytes", models.PositiveBigIntegerField(default=0)),
                ("original_file", models.FileField(max_length=500, upload_to=processor.models.upload_path)),
                ("base_snapshot", models.CharField(blank=True, max_length=500)),
                ("base_columns", models.JSONField(blank=True, default=list)),
                ("row_count", models.PositiveIntegerField(default=0)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={"ordering": ["-created_at"]},
        ),
        migrations.CreateModel(
            name="Operation",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("sequence", models.PositiveIntegerField()),
                (
                    "kind",
                    models.CharField(
                        choices=[
                            ("regex_replace", "Find & replace"),
                            ("standardize", "Standardize values"),
                            ("derive", "Derive new column"),
                        ],
                        max_length=20,
                    ),
                ),
                ("instruction", models.TextField(blank=True)),
                ("pattern", models.TextField(blank=True)),
                ("flags", models.JSONField(blank=True, default=list)),
                ("replacement", models.TextField(blank=True)),
                ("use_backrefs", models.BooleanField(default=False)),
                ("columns", models.JSONField(blank=True, default=list)),
                ("explanation", models.TextField(blank=True)),
                ("stats", models.JSONField(blank=True, default=dict)),
                ("snapshot", models.CharField(max_length=500)),
                ("columns_after", models.JSONField(blank=True, default=list)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "dataset",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="operations",
                        to="processor.dataset",
                    ),
                ),
            ],
            options={
                "ordering": ["sequence"],
                "constraints": [
                    models.UniqueConstraint(fields=("dataset", "sequence"), name="unique_operation_sequence")
                ],
            },
        ),
    ]
