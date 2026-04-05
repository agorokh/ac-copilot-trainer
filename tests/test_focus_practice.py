"""
Pure selection logic for focus practice mode (issue #44).

These tests mirror ``src/ac_copilot_trainer/modules/focus_practice.lua``;
update both when changing behavior.
"""

from __future__ import annotations

import re


def corner_labels_map_from_string(s: str | None) -> dict[str, bool]:
    out: dict[str, bool] = {}
    if not s or not isinstance(s, str):
        return out
    for part in re.split(r"[,;]", s):
        m = re.match(r"^\s*([A-Z]\d+)\s*$", part.strip())
        if m:
            out[m.group(1)] = True
    return out


def label_from_worst_row(row: str | None) -> str | None:
    if not row or not isinstance(row, str):
        return None
    parts = row.split()
    return parts[0] if parts else None


def corner_labels_map_from_worst(
    worst_three: list[str] | None,
    max_n: int | None,
) -> dict[str, bool]:
    out: dict[str, bool] = {}
    # int() truncates toward zero; matches Lua math.floor for non-negative max_n.
    raw_nmax = 3 if max_n is None else int(max_n)
    nmax = max(1, min(3, raw_nmax))
    if not worst_three:
        return out
    for row in worst_three:
        if nmax <= 0:
            break
        lab = label_from_worst_row(row)
        if lab and lab not in out:
            out[lab] = True
            nmax -= 1
    return out


def wrap01(x: float) -> float:
    s = x % 1.0
    # Unreachable in Python (non-negative modulus); mirrors Lua for parity.
    if s < 0:
        s += 1.0
    return s


def spline_dist_wrap(a: float, b: float) -> float:
    a, b = wrap01(a), wrap01(b)
    d = abs(a - b)
    if d > 0.5:
        d = 1.0 - d
    return d


def brake_spline_matches_focus(
    brake_spline: float | None,
    focus_map: dict[str, bool] | None,
    corners: list[dict] | None,
    tol: float = 0.012,
) -> bool:
    if brake_spline is None or not isinstance(brake_spline, (int, float)):
        return False
    if not focus_map or not any(focus_map.values()):
        return False
    if not corners:
        return False
    for c in corners:
        lab = c.get("label")
        if not isinstance(lab, str) or not focus_map.get(lab):
            continue
        bs = c.get("brakePointSpline")
        if bs is None:
            continue
        bs = float(bs)
        if spline_dist_wrap(float(brake_spline), bs) <= tol:
            return True
    return False


def filter_coaching_hints(
    hints: list[dict] | None,
    focus_active: bool,
    focus_map: dict[str, bool] | None,
) -> list[dict]:
    if hints is None or not isinstance(hints, list) or len(hints) == 0:
        return []
    if not focus_active or not focus_map or not any(focus_map.values()):
        return hints

    def mentions_focus(text: str) -> bool:
        for lab in focus_map:
            prefix = f"{lab}:"
            if text.startswith(prefix) or prefix in text:
                return True
        return False

    focused = [h for h in hints if isinstance(h, dict) and mentions_focus(str(h.get("text", "")))]
    if focused:
        return focused
    return [hints[0]]


def test_corner_labels_map_from_string() -> None:
    assert corner_labels_map_from_string("") == {}
    assert corner_labels_map_from_string("T1,T2") == {"T1": True, "T2": True}
    assert corner_labels_map_from_string("t1") == {}  # Lua requires uppercase corner index
    assert corner_labels_map_from_string("T1; T3 ") == {"T1": True, "T3": True}


def test_corner_labels_map_from_worst() -> None:
    w = ["T2 40%", "T1 55%", "T3 70%"]
    assert corner_labels_map_from_worst(w, 2) == {"T2": True, "T1": True}
    assert corner_labels_map_from_worst(w, 5) == {"T2": True, "T1": True, "T3": True}
    assert corner_labels_map_from_worst(w, 0) == {"T2": True}  # Lua clamps 0 -> 1 slot
    assert corner_labels_map_from_worst(w, 2.5) == {"T2": True, "T1": True}  # Lua math.floor


def test_wrap01() -> None:
    assert abs(wrap01(-0.3) - 0.7) < 1e-9
    assert abs(wrap01(1.7) - 0.7) < 1e-9
    assert abs(wrap01(5.3) - 0.3) < 1e-9


def test_spline_dist_wrap() -> None:
    assert abs(spline_dist_wrap(0.95, 0.05) - 0.1) < 1e-9
    assert abs(spline_dist_wrap(0.0, 0.5) - 0.5) < 1e-9
    assert abs(spline_dist_wrap(0.99, 0.01) - 0.02) < 1e-9


def test_brake_spline_matches_focus() -> None:
    corners = [
        {"label": "T1", "brakePointSpline": 0.1},
        {"label": "T2", "brakePointSpline": 0.5},
    ]
    fm = {"T1": True}
    assert brake_spline_matches_focus(0.1, fm, corners) is True
    assert brake_spline_matches_focus(0.11, fm, corners, tol=0.05) is True
    assert brake_spline_matches_focus(0.5, fm, corners) is False


def test_filter_coaching_hints() -> None:
    hints = [
        {"kind": "line", "text": "T1: min speed 80 vs ref 90"},
        {"kind": "throttle", "text": "Coasting 2.0s last lap"},
    ]
    fm = {"T1": True}
    out = filter_coaching_hints(hints, True, fm)
    assert len(out) == 1
    assert "T1" in out[0]["text"]
    assert filter_coaching_hints(hints, False, fm) == hints


def test_filter_fallback_single_hint() -> None:
    hints = [{"kind": "throttle", "text": "Coasting only"}]
    fm = {"T1": True}
    out = filter_coaching_hints(hints, True, fm)
    assert len(out) == 1


def test_filter_empty_and_inactive() -> None:
    assert filter_coaching_hints([], True, {"T1": True}) == []
    assert filter_coaching_hints(None, True, {"T1": True}) == []
    hints = [{"kind": "line", "text": "T1: ok"}]
    assert filter_coaching_hints(hints, True, {}) == hints
    assert filter_coaching_hints(hints, True, None) == hints


def test_filter_no_corner_match_takes_first() -> None:
    hints = [
        {"kind": "throttle", "text": "Coasting 2.0s"},
        {"kind": "throttle", "text": "Full throttle low"},
    ]
    fm = {"T1": True}
    out = filter_coaching_hints(hints, True, fm)
    assert len(out) == 1
    assert out[0]["text"] == "Coasting 2.0s"


def test_filter_skips_non_matching_then_first() -> None:
    hints = [
        {"kind": "throttle", "text": "Generic filler"},
        {"kind": "line", "text": "T2: brake earlier"},
    ]
    fm = {"T2": True}
    out = filter_coaching_hints(hints, True, fm)
    assert len(out) == 1
    assert "T2" in out[0]["text"]
