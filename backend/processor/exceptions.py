"""Domain errors raised by the service layer.

Services never return HTTP responses; they raise these exceptions and the API
layer (``processor.api.exception_handler``) turns them into a consistent JSON
error body: ``{"error": {"code": ..., "message": ..., "details": ...}}``.
"""
from __future__ import annotations

from typing import Any


class ProcessingError(Exception):
    status_code = 400
    code = "processing_error"

    def __init__(self, message: str, *, details: Any = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details


class FileValidationError(ProcessingError):
    code = "invalid_file"


class ColumnError(ProcessingError):
    code = "invalid_column"


class PatternError(ProcessingError):
    status_code = 422
    code = "invalid_pattern"


class OperationTimeout(ProcessingError):
    status_code = 422
    code = "operation_timeout"


class NothingToUndo(ProcessingError):
    status_code = 409
    code = "nothing_to_undo"


class LLMError(ProcessingError):
    status_code = 502
    code = "llm_error"


class LLMNotConfigured(LLMError):
    status_code = 503
    code = "llm_not_configured"
