import json
from pathlib import Path
from typing import Protocol

from .schema import Interpretation


class Interpreter(Protocol):
    def interpret(self, source_version_id: str, text: str) -> Interpretation: ...


class FixtureInterpreter:
    """Only reviewed fixtures; no NLP claims and no HTTP-provided model output."""

    def __init__(self, fixtures=None):
        self.fixtures = fixtures or {}
        self.calls = 0

    @classmethod
    def from_file(cls, path):
        return cls(json.loads(Path(path).read_text()))

    def interpret(self, source_version_id, text):
        self.calls += 1
        output = self.fixtures.get(text)
        if isinstance(output, Exception):
            raise output
        output = output or {"operation": "clarify", "question": "Тестовый адаптер не знает эту фразу. Уточните действие."}
        return Interpretation.model_validate({**output, "source_version_id": source_version_id})


class DeliveryError(Exception):
    """Known not delivered."""


class DeliveryUnknown(Exception):
    """Delivery might have happened; no automatic retry."""


class Transport(Protocol):
    def send(self, delivery_id: str, owner_id: str, text: str) -> str: ...


class FakeTransport:
    def __init__(self, outcome="success"):
        self.outcome = outcome
        self.sent = []

    def send(self, delivery_id, owner_id, text):
        if self.outcome == "error":
            raise DeliveryError()
        if self.outcome == "unknown":
            raise DeliveryUnknown()
        self.sent.append((delivery_id, owner_id, text))
        return f"fake:{delivery_id}"


def real_ai(*, enabled=False, key=None, budget=None, consent=False):
    """Fail closed. Real provider billing and request adapters are not implemented."""
    if not enabled or not key or not budget or not consent:
        raise RuntimeError("Real AI disabled: key, budget and consent required")
    raise RuntimeError("Real AI adapter not implemented")
