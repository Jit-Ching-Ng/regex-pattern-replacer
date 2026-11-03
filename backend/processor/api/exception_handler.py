"""Uniform JSON errors: ``{"error": {"code", "message", "details"}}``."""
from __future__ import annotations

import logging

from django.http import Http404
from rest_framework import exceptions, status
from rest_framework.response import Response
from rest_framework.views import exception_handler

from processor.exceptions import ProcessingError

logger = logging.getLogger(__name__)


def _body(code: str, message: str, details=None) -> dict:
    return {"error": {"code": code, "message": message, "details": details}}


def _first_message(detail) -> str:
    """Pull a human-readable sentence out of DRF's nested error structures."""
    if isinstance(detail, dict):
        for key, value in detail.items():
            message = _first_message(value)
            return message if key == "non_field_errors" else f"{key}: {message}"
    if isinstance(detail, list) and detail:
        return _first_message(detail[0])
    return str(detail)


def api_exception_handler(exc, context):
    if isinstance(exc, ProcessingError):
        return Response(_body(exc.code, exc.message, exc.details), status=exc.status_code)

    if isinstance(exc, exceptions.ValidationError):
        return Response(
            _body("validation_error", _first_message(exc.detail), exc.detail),
            status=status.HTTP_400_BAD_REQUEST,
        )

    response = exception_handler(exc, context)
    if response is not None:
        if isinstance(exc, Http404) or response.status_code == 404:
            response.data = _body("not_found", "The requested dataset does not exist (it may have expired).")
        else:
            code = getattr(exc, "default_code", "error")
            response.data = _body(code, _first_message(response.data))
        return response

    logger.exception("Unhandled error in API view", exc_info=exc)
    return Response(
        _body("server_error", "Something went wrong on the server. The error has been logged."),
        status=status.HTTP_500_INTERNAL_SERVER_ERROR,
    )
