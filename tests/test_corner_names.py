"""
Pure logic tests mirroring ``src/ac_copilot_trainer/modules/corner_names.lua`` (issue #57 Part A).
"""

from __future__ import annotations

import re


def wrap01(x: float) -> float:
    s = x % 1.0
    if s < 0:
        s += 1.0
    return s


def parse_corners_ini(content: str | None) -> dict[int, dict]:
    by_id: dict[int, dict] = {}
    if not content:
        return by_id
    current_id: int | None = None
    for raw in content.splitlines():
        line = raw.strip()
        if not line or line.startswith(";") or line.startswith("#"):
            continue
        if line.startswith("["):
            m = re.match(r"^\[CORNER_(\d+)\]", line)
            current_id = int(m.group(1)) if m else None
            continue
        if current_id is None:
            continue
        if "=" not in line:
            continue
        k, v = line.split("=", 1)
        k, v = k.strip().upper(), v.strip()
        if k == "NAME" and v:
            by_id.setdefault(current_id, {})["name"] = v
    return by_id


def ini_name_for_turn_index(by_id: dict[int, dict], turn_index: int) -> str | None:
    if turn_index < 1:
        return None
    row = by_id.get(turn_index - 1) or by_id.get(turn_index)
    if not row:
        return None
    name = row.get("name")
    return str(name) if name else None


def steer_side_for_range(
    trace: list[dict],
    s0: float,
    s1: float,
    wrap: bool,
) -> str | None:
    if len(trace) < 2:
        return None
    s0, s1 = wrap01(s0), wrap01(s1)
    n, sum_st = 0, 0.0
    for p in trace:
        sp = wrap01(float(p.get("spline", 0)))
        if wrap:
            inside = sp >= s0 or sp < s1
        else:
            inside = s0 <= sp < s1
        if inside:
            sum_st += float(p.get("steer", 0))
            n += 1
    if n == 0:
        return None
    avg = sum_st / n
    if avg > 0.02:
        return "Right"
    if avg < -0.02:
        return "Left"
    return None


def spline_dist(a: float, b: float) -> float:
    a, b = wrap01(a), wrap01(b)
    d = abs(a - b)
    return min(d, 1.0 - d)


def corner_segment_for_brake_spline(
    segments: list[dict],
    brake_spline: float,
    tol: float = 0.012,
) -> dict | None:
    best: dict | None = None
    best_d = float("inf")
    for seg in segments:
        if seg.get("kind") != "corner":
            continue
        bs = seg.get("brakeSpline")
        if not isinstance(bs, (int, float)):
            continue
        d = spline_dist(float(bs), brake_spline)
        if d < best_d:
            best_d = d
            best = seg
    if best is not None and best_d <= tol * 2.5:
        return best
    return None


def corner_label_from_features(
    corners: list[dict],
    brake_spline: float,
    tol: float = 0.012,
) -> str | None:
    for c in corners:
        bps = c.get("brakePointSpline")
        lab = c.get("label")
        if isinstance(bps, (int, float)) and isinstance(lab, str):
            if spline_dist(float(bps), brake_spline) <= tol:
                return lab
    return None


def resolve_approach_label(
    brake_spline: float,
    brake_index: int,
    segments: list[dict] | None,
    ini_by_id: dict[int, dict],
    trace: list[dict] | None,
    corner_feats: list[dict] | None,
    tol: float = 0.012,
) -> str:
    seg = corner_segment_for_brake_spline(segments or [], brake_spline, tol)
    base = "Brake"
    turn_num: int | None = None
    if seg and isinstance(seg.get("label"), str):
        base = str(seg["label"])
        m = re.match(r"^T(\d+)$", base)
        turn_num = int(m.group(1)) if m else None
    else:
        lab = corner_label_from_features(corner_feats or [], brake_spline, tol)
        if lab:
            base = lab
            m2 = re.match(r"^T(\d+)$", lab)
            turn_num = int(m2.group(1)) if m2 else None
        else:
            base = f"T{int(brake_index)}"
            turn_num = int(brake_index)

    ini_name = ini_name_for_turn_index(ini_by_id, turn_num) if turn_num else None
    head = ini_name or base

    side: str | None = None
    if seg and trace and len(trace) >= 2:
        s0 = seg.get("s0")
        s1 = seg.get("s1")
        if isinstance(s0, (int, float)) and isinstance(s1, (int, float)):
            wrap = float(s1) <= float(s0)
            side = steer_side_for_range(trace, float(s0), float(s1), wrap)

    return f"{head} {side}" if side else head


def test_parse_corners_ini_kunos_order() -> None:
    body = "[CORNER_0]\nNAME=First\n[CORNER_1]\nNAME=Second\n"
    by_id = parse_corners_ini(body)
    assert by_id[0]["name"] == "First"
    assert by_id[1]["name"] == "Second"
    assert ini_name_for_turn_index(by_id, 1) == "First"
    assert ini_name_for_turn_index(by_id, 2) == "Second"


def test_parse_ignores_other_sections() -> None:
    body = "[HEADER]\nVERSION=1\n[CORNER_0]\nNAME=Only\n"
    by_id = parse_corners_ini(body)
    assert len(by_id) == 1
    assert ini_name_for_turn_index(by_id, 1) == "Only"


def test_steer_side_left_right() -> None:
    trace = [
        {"spline": 0.1, "steer": -0.3},
        {"spline": 0.11, "steer": -0.25},
        {"spline": 0.12, "steer": -0.28},
    ]
    assert steer_side_for_range(trace, 0.09, 0.13, False) == "Left"
    trace_r = [{"spline": 0.5 + i * 0.001, "steer": 0.2} for i in range(5)]
    assert steer_side_for_range(trace_r, 0.499, 0.506, False) == "Right"


def test_resolve_uses_ini_and_side() -> None:
    ini = parse_corners_ini("[CORNER_0]\nNAME=Variante\n")
    segments = [
        {
            "kind": "corner",
            "label": "T1",
            "brakeSpline": 0.2,
            "s0": 0.19,
            "s1": 0.25,
        }
    ]
    trace = [{"spline": 0.2, "steer": -0.15}, {"spline": 0.22, "steer": -0.18}]
    lab = resolve_approach_label(0.2, 1, segments, ini, trace, None)
    assert "Variante" in lab
    assert "Left" in lab


def test_fallback_t_label_without_ini() -> None:
    lab = resolve_approach_label(0.9, 3, [], {}, [], [])
    assert lab == "T3"
