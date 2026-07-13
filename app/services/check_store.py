"""In-memory staging store for parsed receipts before user confirms save."""

from __future__ import annotations

from typing import Any

# user_id -> staged payload (receipt dict + tmp file paths)
last_check_store: dict[int, dict[str, Any]] = {}


def get_staged(user_id: int) -> dict[str, Any] | None:
    return last_check_store.get(user_id)


def set_staged(user_id: int, payload: dict[str, Any]) -> None:
    last_check_store[user_id] = payload


def pop_staged(user_id: int) -> dict[str, Any] | None:
    return last_check_store.pop(user_id, None)


def clear_staged(user_id: int) -> None:
    last_check_store.pop(user_id, None)
