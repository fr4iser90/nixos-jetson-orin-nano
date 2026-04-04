"""Per-request tenant/user identity for DB-scoped tools (set from HTTP headers)."""

from __future__ import annotations

import contextvars

_identity: contextvars.ContextVar[tuple[int, int] | None] = contextvars.ContextVar(
    "agent_identity", default=None
)


def set_identity(tenant_id: int, user_id: int) -> contextvars.Token:
    return _identity.set((tenant_id, user_id))


def get_identity() -> tuple[int, int]:
    v = _identity.get()
    if v is None:
        return (1, 1)
    return v


def reset_identity(token: contextvars.Token) -> None:
    _identity.reset(token)
