"""
REST endpoints. Each view validates input, calls one service method and
serialises the result; there is no business logic here.

    GET    /api/health/
    POST   /api/datasets/                         upload a CSV/Excel file
    GET    /api/datasets/{id}/                    metadata + columns + history
    DELETE /api/datasets/{id}/
    GET    /api/datasets/{id}/rows/               paginated rows (+ changed cells)
    GET    /api/datasets/{id}/export/?format=csv  download the current version
    POST   /api/datasets/{id}/regex/suggest/      natural language -> regex (+ preview)
    POST   /api/datasets/{id}/regex/preview/      dry-run a pattern
    POST   /api/datasets/{id}/regex/apply/        replace (pattern or natural language)
    POST   /api/datasets/{id}/transform/          LLM standardize / derive column
    POST   /api/datasets/{id}/undo/
    POST   /api/datasets/{id}/reset/
"""
from __future__ import annotations

from django.http import HttpResponse
from django.utils.http import content_disposition_header
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action, api_view
from rest_framework.parsers import JSONParser, MultiPartParser
from rest_framework.request import Request
from rest_framework.response import Response

from processor.api.serializers import (
    DatasetSerializer,
    ExportQuerySerializer,
    OperationSerializer,
    RegexSpecSerializer,
    RegexSuggestSerializer,
    RowsQuerySerializer,
    TransformSerializer,
    UploadSerializer,
)
from processor.models import Dataset
from processor.services.datasets import DatasetService, RegexSpec
from processor.services.llm import llm_status


@api_view(["GET"])
def health(request: Request) -> Response:
    return Response({"status": "ok", "llm": llm_status()})


class DatasetViewSet(
    mixins.RetrieveModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet,
):
    queryset = Dataset.objects.prefetch_related("operations")
    serializer_class = DatasetSerializer
    parser_classes = [JSONParser, MultiPartParser]

    @property
    def service(self) -> DatasetService:
        return DatasetService()

    def _dataset_response(self, dataset: Dataset, **extra) -> Response:
        dataset = Dataset.objects.prefetch_related("operations").get(pk=dataset.pk)
        return Response({"dataset": DatasetSerializer(dataset).data, **extra})

    # ------------------------------------------------------------ CRUD

    def create(self, request: Request) -> Response:
        serializer = UploadSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        dataset = self.service.create(serializer.validated_data["file"])
        response = self._dataset_response(dataset)
        response.status_code = status.HTTP_201_CREATED
        return response

    def perform_destroy(self, instance: Dataset) -> None:
        self.service.delete(instance)

    # ------------------------------------------------------------ reading

    @action(detail=True, methods=["get"])
    def rows(self, request: Request, pk=None) -> Response:
        query = RowsQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        return Response(self.service.rows(self.get_object(), **query.validated_data))

    @action(detail=True, methods=["get"])
    def export(self, request: Request, pk=None) -> HttpResponse:
        query = ExportQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        payload, content_type, filename = self.service.export(self.get_object(), query.validated_data["format"])
        response = HttpResponse(payload, content_type=content_type)
        response["Content-Disposition"] = content_disposition_header(True, filename)
        return response

    # ------------------------------------------------------------ regex

    @action(detail=True, methods=["post"], url_path="regex/suggest")
    def regex_suggest(self, request: Request, pk=None) -> Response:
        """Generate a regex from natural language and preview its effect."""
        body = RegexSuggestSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        data = body.validated_data
        dataset = self.get_object()

        suggestion = self.service.suggest_regex(dataset, data["instruction"], target_columns=data["columns"])
        spec = RegexSpec(
            pattern=suggestion.pattern,
            flags=suggestion.flags,
            replacement=_effective_replacement(data.get("replacement"), suggestion.replacement),
            columns=suggestion.columns,
            use_backrefs=data["use_backrefs"],
        )
        preview = self.service.preview_regex(dataset, spec)
        return Response({"suggestion": suggestion.as_dict(), "preview": preview})

    @action(detail=True, methods=["post"], url_path="regex/preview")
    def regex_preview(self, request: Request, pk=None) -> Response:
        spec = self._resolve_spec(request)
        return Response({"preview": self.service.preview_regex(self.get_object(), spec)})

    @action(detail=True, methods=["post"], url_path="regex/apply")
    def regex_apply(self, request: Request, pk=None) -> Response:
        """Apply a replacement. Accepts a ready pattern, or only an instruction
        (the regex is then generated by the LLM in the same request)."""
        spec = self._resolve_spec(request)
        operation = self.service.apply_regex(self.get_object(), spec)
        return self._dataset_response(operation.dataset, operation=OperationSerializer(operation).data)

    def _resolve_spec(self, request: Request) -> RegexSpec:
        body = RegexSpecSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        data = body.validated_data
        if data.get("pattern"):
            return RegexSpec(
                pattern=data["pattern"],
                flags=data["flags"],
                replacement=data.get("replacement") or "",
                columns=data["columns"],
                use_backrefs=data["use_backrefs"],
                instruction=data["instruction"],
                explanation=data["explanation"],
            )
        suggestion = self.service.suggest_regex(self.get_object(), data["instruction"], target_columns=data["columns"])
        return RegexSpec(
            pattern=suggestion.pattern,
            flags=suggestion.flags,
            replacement=_effective_replacement(data.get("replacement"), suggestion.replacement),
            columns=suggestion.columns,
            use_backrefs=data["use_backrefs"],
            instruction=data["instruction"],
            explanation=suggestion.explanation,
        )

    # ------------------------------------------------------------ transforms & history

    @action(detail=True, methods=["post"])
    def transform(self, request: Request, pk=None) -> Response:
        body = TransformSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        data = body.validated_data
        operation, samples = self.service.apply_transform(
            self.get_object(),
            kind=data["kind"],
            column=data["column"],
            instruction=data["instruction"],
            new_column=data["new_column"],
        )
        return self._dataset_response(
            operation.dataset, operation=OperationSerializer(operation).data, samples=samples
        )

    @action(detail=True, methods=["post"])
    def undo(self, request: Request, pk=None) -> Response:
        dataset = self.get_object()
        undone = self.service.undo(dataset)
        return self._dataset_response(dataset, undone=undone)

    @action(detail=True, methods=["post"])
    def reset(self, request: Request, pk=None) -> Response:
        dataset = self.get_object()
        removed = self.service.reset(dataset)
        return self._dataset_response(dataset, removed_operations=removed)


def _effective_replacement(requested: str | None, suggested: str | None) -> str:
    """An explicit replacement (even "") wins; else the one stated in the sentence."""
    if requested is not None:
        return requested
    return suggested or ""
