"""Scoped progress reporting without changing the discovered extractor contract."""
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Callable

_callback: ContextVar[Callable[[str], None] | None] = ContextVar("extraction_progress", default=None)


def report_progress(message: str) -> None:
    callback = _callback.get()
    if callback:
        callback(message)


@contextmanager
def progress_scope(callback):
    token = _callback.set(callback)
    try:
        yield
    finally:
        _callback.reset(token)
