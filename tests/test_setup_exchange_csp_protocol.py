"""The internal Setup Exchange RPC carries bounded public data, never client authority."""

from __future__ import annotations

import pytest

from tools.ai_sidecar.external_protocol import (
    MAX_SETUP_EXCHANGE_CSP_BYTES,
    TYPE_SETUP_EXCHANGE_CSP_REQUEST,
    TYPE_SETUP_EXCHANGE_CSP_RESULT,
    validate_inbound,
)


def result(**changes):
    return {
        "v": 1,
        "type": TYPE_SETUP_EXCHANGE_CSP_RESULT,
        "request_id": "a" * 32,
        "operation": "search",
        "ok": True,
        "response": [{"setupID": 86, "name": "Race", "userName": "Community author"}],
        **changes,
    }


def test_internal_request_is_never_a_client_command():
    assert "server-to-trainer" in validate_inbound({"v": 1, "type": TYPE_SETUP_EXCHANGE_CSP_REQUEST})


@pytest.mark.parametrize(
    "changes",
    [
        {},
        {"operation": "download", "response": {"data": "[HEADER]\nVERSION=1"}},
        {"ok": False, "error": "Setup Exchange session unavailable", "response": None},
        {"total_count": 100},
    ],
)
def test_valid_public_result_shape(changes):
    assert validate_inbound(result(**changes)) is None


@pytest.mark.parametrize(
    "changes",
    [
        {"request_id": "a" * 33},
        {"request_id": "not-a-request-id"},
        {"operation": "session"},
        {"ok": 1},
        {"response": "raw text"},
        {"operation": "download", "response": []},
        {"total_count": True},
        {"total_count": -1},
        {"ok": False, "error": ""},
        {"ok": False, "error": "secret\nmaterial"},
        {"ok": False, "error": "x" * 241},
        {"sessionID": "must-stay-in-CSP"},
        {"response": {"value": float("nan")}},
    ],
)
def test_invalid_result_shape_rejected(changes):
    assert validate_inbound(result(**changes)) is not None


def test_result_size_is_bounded():
    assert "limit" in validate_inbound(result(response={"data": "x" * MAX_SETUP_EXCHANGE_CSP_BYTES}))
