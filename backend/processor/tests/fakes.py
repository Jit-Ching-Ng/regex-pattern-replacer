"""Test doubles."""
from __future__ import annotations

import json
from typing import Callable

from processor.services.llm import LLMClient


class FakeLLM(LLMClient):
    """Returns scripted replies (strings, dicts or callables) in order."""

    provider = "fake"

    def __init__(self, *replies: str | dict | Callable[[str, list], str | dict]) -> None:
        super().__init__(model="fake", timeout=1)
        self.replies = list(replies)
        self.calls: list[dict] = []

    def complete(self, system, messages, *, max_tokens=1024):
        self.calls.append({"system": system, "messages": [dict(m) for m in messages]})
        if not self.replies:
            raise AssertionError("FakeLLM ran out of scripted replies")
        reply = self.replies.pop(0)
        if callable(reply):
            reply = reply(system, messages)
        return json.dumps(reply) if isinstance(reply, dict) else reply


def echo_transform(fn: Callable[[str], str]):
    """A FakeLLM reply that applies ``fn`` to every value in the request."""

    def reply(system, messages):
        payload = messages[-1]["content"].split("Values:\n", 1)[1].rsplit("\n\nReply", 1)[0]
        items = json.loads(payload)
        return {"results": [{"id": item["id"], "value": fn(item["value"])} for item in items]}

    return reply
