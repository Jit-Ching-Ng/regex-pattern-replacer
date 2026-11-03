"""Request validation and response shapes for the REST API."""
from __future__ import annotations

from rest_framework import serializers

from processor.models import Dataset, Operation
from processor.services.regex_engine import SUPPORTED_FLAGS
from processor.services.transforms import DERIVE, STANDARDIZE

MAX_INSTRUCTION_LENGTH = 1000


# ---------------------------------------------------------------- responses


class OperationSerializer(serializers.ModelSerializer):
    kind_label = serializers.CharField(source="get_kind_display", read_only=True)

    class Meta:
        model = Operation
        fields = [
            "id",
            "sequence",
            "kind",
            "kind_label",
            "instruction",
            "pattern",
            "flags",
            "replacement",
            "use_backrefs",
            "columns",
            "explanation",
            "stats",
            "created_at",
        ]


class DatasetSerializer(serializers.ModelSerializer):
    columns = serializers.JSONField(source="current_columns", read_only=True)
    operations = OperationSerializer(many=True, read_only=True)

    class Meta:
        model = Dataset
        fields = ["id", "name", "file_type", "size_bytes", "row_count", "columns", "operations", "created_at"]


# ---------------------------------------------------------------- requests


class UploadSerializer(serializers.Serializer):
    file = serializers.FileField(allow_empty_file=False)


class RowsQuerySerializer(serializers.Serializer):
    page = serializers.IntegerField(min_value=1, default=1)
    page_size = serializers.IntegerField(min_value=1, max_value=500, default=50)
    highlight = serializers.BooleanField(default=False)


class ExportQuerySerializer(serializers.Serializer):
    format = serializers.ChoiceField(choices=["csv", "xlsx"], default="csv")


class _ColumnsField(serializers.ListField):
    def __init__(self, **kwargs):
        super().__init__(child=serializers.CharField(max_length=255), required=False, default=list, **kwargs)


class RegexSuggestSerializer(serializers.Serializer):
    instruction = serializers.CharField(max_length=MAX_INSTRUCTION_LENGTH, trim_whitespace=True)
    columns = _ColumnsField()
    # Optional: lets the response include a preview computed with this value.
    replacement = serializers.CharField(required=False, allow_blank=True, allow_null=True, trim_whitespace=False)
    use_backrefs = serializers.BooleanField(default=False)


class RegexSpecSerializer(serializers.Serializer):
    """A concrete pattern (preview), optionally generated from ``instruction`` (apply)."""

    instruction = serializers.CharField(
        max_length=MAX_INSTRUCTION_LENGTH, required=False, allow_blank=True, default=""
    )
    pattern = serializers.CharField(max_length=2000, required=False, allow_blank=True, trim_whitespace=False)
    flags = serializers.ListField(
        child=serializers.ChoiceField(choices=list(SUPPORTED_FLAGS)), required=False, default=list
    )
    replacement = serializers.CharField(required=False, allow_blank=True, allow_null=True, trim_whitespace=False)
    columns = _ColumnsField()
    use_backrefs = serializers.BooleanField(default=False)
    explanation = serializers.CharField(max_length=500, required=False, allow_blank=True, default="")

    def validate(self, attrs):
        if not attrs.get("pattern") and not attrs.get("instruction"):
            raise serializers.ValidationError("Provide a regex 'pattern' or a natural-language 'instruction'.")
        return attrs


class TransformSerializer(serializers.Serializer):
    kind = serializers.ChoiceField(choices=[STANDARDIZE, DERIVE])
    column = serializers.CharField(max_length=255)
    instruction = serializers.CharField(max_length=MAX_INSTRUCTION_LENGTH)
    new_column = serializers.CharField(max_length=255, required=False, allow_blank=True, default="")

    def validate(self, attrs):
        if attrs["kind"] == DERIVE and not attrs["new_column"].strip():
            raise serializers.ValidationError({"new_column": "A name for the new column is required."})
        return attrs
