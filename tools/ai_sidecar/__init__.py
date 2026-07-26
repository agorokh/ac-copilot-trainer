"""Minimal WebSocket sidecar for AC Copilot Trainer (issue #9 Part B)."""

from typing import Any


def main(*args: Any, **kwargs: Any) -> Any:
    """Load the server lazily so sidecar utility modules remain standalone CLIs."""

    from .server import main as server_main

    return server_main(*args, **kwargs)


__all__ = ["main"]
