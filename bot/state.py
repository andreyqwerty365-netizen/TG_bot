from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .views import MAIN


@dataclass(slots=True)
class ChatState:
    menu: str = MAIN
    mode: str | None = None
    payload: dict[str, Any] = field(default_factory=dict)


def get_chat_state(store: dict[int, ChatState], chat_id: int) -> ChatState:
    if chat_id not in store:
        store[chat_id] = ChatState()
    return store[chat_id]


def set_mode(store: dict[int, ChatState], chat_id: int, mode: str | None, **payload: Any) -> ChatState:
    state = get_chat_state(store, chat_id)
    state.mode = mode
    state.payload = payload
    return state
