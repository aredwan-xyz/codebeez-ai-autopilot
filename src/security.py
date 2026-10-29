"""Authentication and per-execution approval for integration mutations."""

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from secrets import compare_digest

from src.config.settings import settings


@dataclass
class _Approval:
    active: bool = True


_approved_execution = ContextVar("approved_execution", default=None)


def valid_admin_token(token: str) -> bool:
    configured = settings.ADMIN_API_TOKEN
    return bool(configured and token and compare_digest(token.encode(), configured.encode()))


def require_live_approval() -> None:
    """Fail closed even when a caller bypasses an agent's dry-run branch."""
    scope = _approved_execution.get()
    if not settings.ENABLE_LIVE_ACTIONS or scope is None or not scope.active:
        raise PermissionError("Live writes require ENABLE_LIVE_ACTIONS and an approved API execution")


@contextmanager
def approved_execution():
    """Only the authenticated, explicitly approved trigger enters this scope."""
    if not settings.ENABLE_LIVE_ACTIONS:
        raise PermissionError("Live actions are disabled")
    scope = _Approval()
    token = _approved_execution.set(scope)
    try:
        yield
    finally:
        scope.active = False
        _approved_execution.reset(token)
