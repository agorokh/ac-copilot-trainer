"""Package smoke tests for optional AI WebSocket sidecar (issue #9 Part B)."""

import importlib

import pytest


def test_ai_sidecar_subpackage_importable() -> None:
    importlib.import_module("tools.ai_sidecar")


def test_ai_sidecar_server_import_requires_websockets() -> None:
    pytest.importorskip("websockets")
    importlib.import_module("tools.ai_sidecar.server")
