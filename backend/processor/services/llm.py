"""
A small, provider-agnostic LLM client.

The rest of the code base only depends on :class:`LLMClient.complete`, so the
provider can be swapped through configuration (``LLM_PROVIDER``) and tests can
inject a fake client without patching HTTP calls.

Two adapters are included:

* :class:`AnthropicClient` - Anthropic Messages API.
* :class:`OpenAICompatibleClient` - the ``/chat/completions`` API spoken by
  OpenAI and many others (Groq, Together, OpenRouter, Ollama, vLLM, ...).

Plain ``requests`` is used instead of vendor SDKs to keep dependencies small and
the request/response handling explicit.
"""
from __future__ import annotations

import json
import logging
import re
from abc import ABC, abstractmethod
from typing import Any

import requests
from django.conf import settings

from processor.exceptions import LLMError, LLMNotConfigured

logger = logging.getLogger(__name__)

Message = dict[str, str]  # {"role": "user" | "assistant", "content": "..."}

DEFAULT_MODELS = {
    "anthropic": "claude-haiku-5-5",
    "openai": "gpt-4o-mini",
}


class LLMClient(ABC):
    """Minimal interface: send a system prompt + chat history, get text back."""

    provider: str = "unknown"

    def __init__(self, *, model: str, timeout: float) -> None:
        self.model = model
        self.timeout = timeout
        self._session = requests.Session()

    @abstractmethod
    def complete(self, system: str, messages: list[Message], *, max_tokens: int = 1024) -> str:
        """Return the model's text reply. Raises :class:`LLMError` on failure."""

    def _post(self, url: str, headers: dict[str, str], payload: dict[str, Any]) -> dict[str, Any]:
        try:
            response = self._session.post(url, headers=headers, json=payload, timeout=self.timeout)
        except requests.Timeout as exc:
            raise LLMError(f"The language model did not answer within {self.timeout:.0f} seconds.") from exc
        except requests.RequestException as exc:
            raise LLMError("Could not reach the language model provider.") from exc

        if response.status_code >= 400:
            detail = _extract_provider_error(response)
            logger.warning("LLM provider error %s: %s", response.status_code, detail)
            if response.status_code in (401, 403):
                raise LLMNotConfigured("The LLM API key was rejected by the provider.", details=detail)
            if response.status_code == 429:
                raise LLMError("The LLM provider is rate limiting requests. Try again shortly.", details=detail)
            raise LLMError("The LLM provider returned an error.", details=detail)

        try:
            return response.json()
        except ValueError as exc:
            raise LLMError("The LLM provider returned a non-JSON response.") from exc


class AnthropicClient(LLMClient):
    provider = "anthropic"
    DEFAULT_BASE_URL = "https://api.anthropic.com/v1"
    API_VERSION = "2023-06-01"

    def __init__(self, *, api_key: str, model: str, timeout: float, base_url: str = "") -> None:
        super().__init__(model=model, timeout=timeout)
        self._api_key = api_key
        self._base_url = (base_url or self.DEFAULT_BASE_URL).rstrip("/")

    def complete(self, system: str, messages: list[Message], *, max_tokens: int = 1024) -> str:
        data = self._post(
            f"{self._base_url}/messages",
            headers={
                "x-api-key": self._api_key,
                "anthropic-version": self.API_VERSION,
                "content-type": "application/json",
            },
            payload={
                "model": self.model,
                "max_tokens": max_tokens,
                "system": system,
                "messages": messages,
            },
        )
        blocks = data.get("content") or []
        text = "".join(block.get("text", "") for block in blocks if block.get("type") == "text")
        if not text:
            raise LLMError("The language model returned an empty answer.")
        return text


class OpenAICompatibleClient(LLMClient):
    provider = "openai"
    DEFAULT_BASE_URL = "https://api.openai.com/v1"

    def __init__(self, *, api_key: str, model: str, timeout: float, base_url: str = "") -> None:
        super().__init__(model=model, timeout=timeout)
        self._api_key = api_key
        self._base_url = (base_url or self.DEFAULT_BASE_URL).rstrip("/")

    def complete(self, system: str, messages: list[Message], *, max_tokens: int = 1024) -> str:
        headers = {"content-type": "application/json"}
        if self._api_key:
            headers["authorization"] = f"Bearer {self._api_key}"
        data = self._post(
            f"{self._base_url}/chat/completions",
            headers=headers,
            payload={
                "model": self.model,
                "max_tokens": max_tokens,
                "temperature": 0,
                "messages": [{"role": "system", "content": system}, *messages],
            },
        )
        try:
            text = data["choices"][0]["message"]["content"] or ""
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMError("Unexpected response shape from the LLM provider.") from exc
        if not text:
            raise LLMError("The language model returned an empty answer.")
        return text


_PROVIDERS: dict[str, type[LLMClient]] = {
    "anthropic": AnthropicClient,
    "openai": OpenAICompatibleClient,
}


def llm_status() -> dict[str, Any]:
    """Configuration summary exposed on the health endpoint (no secrets)."""
    provider = settings.LLM_PROVIDER
    return {
        "provider": provider,
        "model": settings.LLM_MODEL or DEFAULT_MODELS.get(provider, ""),
        "configured": provider in _PROVIDERS and bool(settings.LLM_API_KEY or settings.LLM_BASE_URL),
    }


def get_llm_client() -> LLMClient:
    """Build the client configured in settings. Raises if it is unusable."""
    provider = settings.LLM_PROVIDER
    client_cls = _PROVIDERS.get(provider)
    if client_cls is None:
        raise LLMNotConfigured(
            f"Unknown LLM_PROVIDER '{provider}'. Use one of: {', '.join(sorted(_PROVIDERS))}."
        )
    # A key is mandatory except for self-hosted OpenAI-compatible servers.
    if not settings.LLM_API_KEY and not (provider == "openai" and settings.LLM_BASE_URL):
        raise LLMNotConfigured("No LLM API key is configured on the server (set LLM_API_KEY).")
    return client_cls(
        api_key=settings.LLM_API_KEY,
        model=settings.LLM_MODEL or DEFAULT_MODELS[provider],
        timeout=settings.LLM_TIMEOUT_SECONDS,
        base_url=settings.LLM_BASE_URL,
    )


_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE)


def parse_json_object(text: str) -> dict[str, Any]:
    """Parse a JSON object out of an LLM reply.

    Models occasionally wrap JSON in Markdown fences or add a sentence around
    it, so this strips fences and falls back to the outermost ``{...}`` span.
    """
    cleaned = _FENCE_RE.sub("", text.strip())
    candidates = [cleaned]
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start != -1 and end > start:
        candidates.append(cleaned[start : end + 1])
    for candidate in candidates:
        try:
            value = json.loads(candidate)
        except ValueError:
            continue
        if isinstance(value, dict):
            return value
    raise LLMError("The language model did not return valid JSON.", details=text[:500])


def _extract_provider_error(response: requests.Response) -> str:
    try:
        body = response.json()
    except ValueError:
        return response.text[:300]
    error = body.get("error") if isinstance(body, dict) else None
    if isinstance(error, dict):
        return str(error.get("message") or error)[:300]
    return str(error or body)[:300]
