"""Bounded, connection-scoped RPC to the authenticated trainer's CSP service client."""

from __future__ import annotations

import asyncio
import json
import secrets
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from tools.ai_sidecar.se_proxy import (
    ENV_USER_SETUPS_DIR,
    MAX_SETUP_BYTES,
    SetupExchangeError,
    _normalize_setup_rows,
    _safe_int,
    _safe_search_text,
    _safe_segment,
    _total_from_payload,
    discover_user_setups_root,
    install_setup,
)


def request_fields(data: dict[str, Any], operation: str) -> dict[str, Any]:
    fields: dict[str, Any] = {}
    for key in ("car_id", "track_id"):
        if data.get(key):
            fields[key] = _safe_segment(data[key], key)
    if operation == "download":
        fields["setup_id"] = data["setup_id"]
    else:
        for key in ("search", "order_by"):
            value = _safe_search_text(data.get(key), key)
            if value:
                fields[key] = value
        fields["offset"] = _safe_int(
            data.get("offset"), "offset", default=0, min_value=0, max_value=10_000
        )
        fields["limit"] = _safe_int(
            data.get("limit"), "limit", default=20, min_value=1, max_value=40
        )
    return fields


def _screen_text(value: Any, limit: int) -> str:
    return "".join(c for c in str(value) if c.isprintable())[:limit]


def search_response(data: dict[str, Any], frame: dict[str, Any]) -> dict[str, Any]:
    rows = _normalize_setup_rows(frame.get("response"))[: data.get("limit", 20)]
    for row in rows:
        for key, limit in (("name", 96), ("author", 64), ("car_id", 96), ("track_id", 96)):
            row[key] = _screen_text(row[key], limit)
        row["created_at"] = _screen_text(row["created_at"], 40)
    total = frame.get("total_count")
    if isinstance(total, bool) or not isinstance(total, int) or total < 0:
        total = max(0, _total_from_payload(frame.get("response"), {}, len(rows)))
    return {
        "ok": True,
        "source": "csp",
        "car_id": data.get("car_id"),
        "track_id": data.get("track_id"),
        "offset": data.get("offset", 0),
        "limit": data.get("limit", 20),
        "count": len(rows),
        "total": total,
        "setups": rows,
    }


def fit_screen_response(frame: dict[str, Any]) -> dict[str, Any]:
    # Leave room below the physical serial reader's 8192-byte line ceiling.
    while len(json.dumps(frame, separators=(",", ":")).encode("utf-8")) > 7600:
        if not frame.get("setups"):
            raise SetupExchangeError("Setup Exchange result exceeds the screen message limit")
        frame["setups"].pop()
        frame["count"] = len(frame["setups"])
    return frame


def install_response(
    data: dict[str, Any], frame: dict[str, Any], user_setups_root: Path | None
) -> dict[str, Any]:
    raw = frame.get("response")
    if not isinstance(raw, dict) or not isinstance(raw.get("data"), str):
        raise SetupExchangeError("Setup Exchange download did not include setup data")
    if len(raw["data"].encode("utf-8")) > MAX_SETUP_BYTES:
        raise SetupExchangeError("downloaded setup is too large")
    actual_id = raw.get("setupID", raw.get("setup_id"))
    if actual_id is not None and (
        isinstance(actual_id, bool) or str(actual_id) != str(data["setup_id"])
    ):
        raise SetupExchangeError("downloaded setup does not match requested setup_id")
    for key, official in (("car_id", "carID"), ("track_id", "trackID")):
        actual = raw.get(official) or raw.get(key)
        if actual and actual != data.get(key):
            raise SetupExchangeError(f"downloaded setup does not match requested {key}")
    root = user_setups_root or discover_user_setups_root()
    if root is None:
        raise SetupExchangeError(f"set {ENV_USER_SETUPS_DIR} to your Assetto Corsa setups folder")
    name = data.get("name") or raw.get("name")
    if name is not None and not isinstance(name, str):
        raise SetupExchangeError("downloaded setup name must be text")
    installed = install_setup(
        user_setups_root=root,
        car_id=data["car_id"],
        track_id=data.get("track_id"),
        setup_id=data["setup_id"],
        setup_data=raw["data"],
        setup_name=name,
    )
    return {"ok": True, "source": "csp", "root": str(root), **installed}


@dataclass
class PendingRequest:
    requester: Any
    producer: Any
    operation: str
    future: asyncio.Future[dict[str, Any]]


class SetupExchangeBroker:
    """Keep raw CSP responses private to the original authenticated request."""

    def __init__(self, *, timeout_s: float = 45.0, max_pending: int = 16) -> None:
        self.timeout_s = timeout_s
        self.max_pending = max_pending
        self.pending: dict[str, PendingRequest] = {}

    def begin(self, requester: Any, producer: Any, operation: str) -> str:
        if len(self.pending) >= self.max_pending or any(
            item.requester is requester for item in self.pending.values()
        ):
            raise SetupExchangeError("Setup Exchange request already pending; try again shortly")
        request_id = secrets.token_hex(16)
        self.pending[request_id] = PendingRequest(
            requester, producer, operation, asyncio.get_running_loop().create_future()
        )
        return request_id

    async def wait(self, request_id: str) -> dict[str, Any]:
        try:
            return await asyncio.wait_for(self.pending[request_id].future, self.timeout_s)
        except TimeoutError as exc:
            raise SetupExchangeError(
                "Setup Exchange CSP request timed out; retry in practice"
            ) from exc
        finally:
            self.pending.pop(request_id, None)

    def accept(self, producer: Any, frame: dict[str, Any]) -> bool:
        pending = self.pending.get(frame.get("request_id", ""))
        if (
            pending is None
            or pending.producer is not producer
            or pending.operation != frame.get("operation")
            or pending.future.done()
        ):
            return False
        pending.future.set_result(frame)
        return True

    def drop(self, peer: Any) -> None:
        for request_id, item in list(self.pending.items()):
            if item.requester is peer:
                if not item.future.done():
                    item.future.cancel()
                self.pending.pop(request_id, None)
            elif item.producer is peer and not item.future.done():
                item.future.set_exception(
                    SetupExchangeError("Setup Exchange trainer disconnected; reopen practice")
                )

    def reset(self) -> None:
        for item in self.pending.values():
            if not item.future.done():
                item.future.cancel()
        self.pending.clear()
