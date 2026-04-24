#!/usr/bin/env python3
"""Merge `.claude/settings.base.json` + `.claude/settings.local.json` → `.claude/settings.json`.

Hook lists under each matcher group are merged: base first, then local overrides by hook
identity (type + stable fingerprint of command/prompt text). Duplicate *command* hooks
(same command string) are deduped, keeping the first occurrence in merged order.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import sys
from pathlib import Path
from typing import Any


def _fingerprint(hook: dict[str, Any]) -> tuple[str, str]:
    """Stable identity for override semantics (same matcher group)."""
    htype = str(hook.get("type", ""))
    if htype == "command":
        body = str(hook.get("command", ""))
    elif htype in ("prompt", "agent"):
        body = str(hook.get("prompt", ""))
    else:
        body = json.dumps(hook, sort_keys=True)
    digest = hashlib.sha256(body.encode("utf-8")).hexdigest()
    return htype, digest


def _merge_hook_lists(
    base_hooks: list[dict[str, Any]], local_hooks: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = [dict(h) for h in base_hooks]
    index_by_fp: dict[tuple[str, str], int] = {}
    for i, h in enumerate(merged):
        fp = _fingerprint(h)
        if fp not in index_by_fp:
            index_by_fp[fp] = i
    for raw in local_hooks:
        h_copy = dict(raw)
        fp = _fingerprint(h_copy)
        if fp in index_by_fp:
            merged[index_by_fp[fp]] = h_copy
        else:
            index_by_fp[fp] = len(merged)
            merged.append(h_copy)

    seen_cmd: set[str] = set()
    out: list[dict[str, Any]] = []
    for h in merged:
        if h.get("type") == "command":
            ch = hashlib.sha256(str(h.get("command", "")).encode("utf-8")).hexdigest()
            if ch in seen_cmd:
                continue
            seen_cmd.add(ch)
        out.append(h)
    return out


def _matcher_alignment_error(i: int, base_m: Any, local_m: Any) -> ValueError:
    return ValueError(
        f"merge_settings: hooks block {i} matcher mismatch: base={base_m!r}, local={local_m!r}"
    )


def _assert_group_matcher_aligned(
    i: int, base_group: dict[str, Any], local_group: dict[str, Any]
) -> None:
    """Local overlay must not contradict the base group's matcher (positional merge)."""
    has_bm = "matcher" in base_group
    has_lm = "matcher" in local_group
    if has_lm and not has_bm:
        raise ValueError(
            f"merge_settings: hooks block {i} has matcher in local but base has none "
            "(cannot attach local matcher to a base block without matcher)"
        )
    if has_bm and has_lm and local_group["matcher"] != base_group["matcher"]:
        raise _matcher_alignment_error(i, base_group.get("matcher"), local_group.get("matcher"))


def _merge_event_groups(
    base_groups: list[dict[str, Any]],
    local_groups: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Align by **positional** matcher blocks (template may repeat the same matcher)."""
    out: list[dict[str, Any]] = []
    for i, bg in enumerate(base_groups):
        lg = local_groups[i] if i < len(local_groups) else {}
        if isinstance(lg, dict) and lg:
            _assert_group_matcher_aligned(i, bg, lg)
        lh = lg.get("hooks") if isinstance(lg, dict) else []
        hooks = _merge_hook_lists(list(bg.get("hooks") or []), list(lh or []))
        new_g = {k: v for k, v in bg.items() if k != "hooks"}
        new_g["hooks"] = hooks
        out.append(new_g)
    for j in range(len(base_groups), len(local_groups)):
        g = local_groups[j]
        out.append(copy.deepcopy(g) if isinstance(g, dict) else {})
    return out


def merge_settings_dict(base: dict[str, Any], local: dict[str, Any]) -> dict[str, Any]:
    base_hooks = base.get("hooks") or {}
    local_hooks = local.get("hooks") or {}

    key_order: list[str] = list(base_hooks.keys())
    for k in local_hooks:
        if k not in key_order:
            key_order.append(k)

    merged_hooks: dict[str, Any] = {}
    for name in key_order:
        merged_hooks[name] = _merge_event_groups(
            list(base_hooks.get(name, []) or []),
            list(local_hooks.get(name, []) or []),
        )

    out = {k: v for k, v in base.items() if k != "hooks"}
    out["hooks"] = merged_hooks
    out.update({k: v for k, v in local.items() if k != "hooks"})
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    root = Path(__file__).resolve().parent.parent
    parser.add_argument(
        "--base",
        type=Path,
        default=root / ".claude" / "settings.base.json",
        help="Template-canonical base JSON",
    )
    parser.add_argument(
        "--local",
        type=Path,
        default=root / ".claude" / "settings.local.json",
        help="Per-repo overlay (optional; missing = empty)",
    )
    parser.add_argument(
        "--no-local",
        action="store_true",
        help="Ignore settings.local.json (reproducible template output for commits)",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=root / ".claude" / "settings.json",
        help="Generated settings path",
    )
    args = parser.parse_args()

    try:
        base_text = args.base.read_text(encoding="utf-8")
    except OSError as e:
        print(f"merge_settings: cannot read base: {e}", file=sys.stderr)
        return 1
    try:
        base = json.loads(base_text)
    except json.JSONDecodeError as e:
        print(f"merge_settings: invalid JSON in base: {e}", file=sys.stderr)
        return 1

    local: dict[str, Any] = {}
    if not args.no_local and args.local.is_file():
        try:
            local = json.loads(args.local.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as e:
            print(f"merge_settings: cannot read/parse local: {e}", file=sys.stderr)
            return 1

    merged = merge_settings_dict(base, local)
    out_text = json.dumps(merged, indent=2, ensure_ascii=False) + "\n"
    try:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(out_text, encoding="utf-8")
    except OSError as e:
        print(f"merge_settings: cannot write output: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
