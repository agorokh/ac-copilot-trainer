"""Tests for wiring the attribution brain into the live debrief path (#275).

Covers coach_report.build_structured_debrief (the machine-readable brain output) and
protocol.build_brain_followup (the non-blocking lap_complete follow-up that resolves the lap
archive from an inline trace or a safe archivePath).
"""

from __future__ import annotations

import json
import math

from tools.ai_sidecar.coach_report import build_structured_debrief
from tools.ai_sidecar.protocol import build_brain_followup

_ENABLE = "AC_COPILOT_OLLAMA_ENABLE"


def _corner_archive(*, degrade: float = 0.0) -> dict:
    """A straight→corner→straight lap archive with a full trace (one clean apex)."""
    radius, ds, n_pre, n_arc, n_post = 30.0, 2.0, 40, 30, 40
    n = n_pre + n_arc + n_post
    kappa = [0.0] * n_pre + [1.0 / radius] * n_arc + [0.0] * n_post
    theta, x, z = 0.0, 0.0, 0.0
    xs, zs = [], []
    for i in range(n):
        xs.append(x)
        zs.append(z)
        theta += kappa[i] * ds
        x += ds * math.cos(theta)
        z += ds * math.sin(theta)
    apex_i = n_pre + n_arc // 2
    v = []
    for i in range(n):
        if i < 25:
            v.append(55.0)
        elif i < apex_i:
            v.append(55.0 + (25.0 - 55.0) * (i - 25) / max(1, apex_i - 25) - degrade)
        elif i < n_pre + n_arc + 5:
            v.append(25.0 + (55.0 - 25.0) * (i - apex_i) / max(1, n_pre + n_arc + 5 - apex_i))
        else:
            v.append(55.0)
    brake = [0.8 if 25 <= i < apex_i else 0.0 for i in range(n)]
    throttle = [1.0 if i >= apex_i + 1 else 0.0 for i in range(n)]
    steer = [0.4 if n_pre <= i < n_pre + n_arc else 0.0 for i in range(n)]
    t_ms = [0.0]
    for i in range(1, n):
        t_ms.append(t_ms[-1] + ds / max(0.5, 0.5 * (v[i] + v[i - 1])) * 1000.0)
    total = ds * (n - 1)
    spline = [(ds * i) / total for i in range(n)]
    samples = [
        [spline[i], v[i] * 3.6, t_ms[i], throttle[i], brake[i], steer[i], 4, xs[i], 0.0, zs[i]]
        for i in range(n)
    ]
    return {
        "event": "lap_complete",
        "lap": 3,
        "car": {"id": "ks_porsche_911_gt3_r_2016"},
        "track": {"id": "magione", "lengthM": total},
        "lap_obj": {"lap_ms": int(t_ms[-1]), "is_valid": True},
        "setup": {"snapshot": {"FRONT_BIAS.VALUE": "66", "TRACTION_CONTROL.VALUE": "4"}},
        "trace": {
            "fields": [
                "spline",
                "speed",
                "eMs",
                "throttle",
                "brake",
                "steer",
                "gear",
                "px",
                "py",
                "pz",
            ],
            "samples": samples,
        },
    }


# --- build_structured_debrief ----------------------------------------------
def test_structured_debrief_has_corners_and_cause_classes():
    out = build_structured_debrief(_corner_archive(), grip_ceiling_g=2.5)
    assert out is not None
    assert "Coaching debrief" in out["text"]
    assert out["corners"]
    c0 = out["corners"][0]
    assert {"index", "headline", "attributions"} <= c0.keys()
    for a in c0["attributions"]:
        assert a["cause_class"] in ("setup", "technique", "grip", "setup+technique", "unknown")
        assert 0.0 <= a["confidence"] <= 1.0
        assert isinstance(a["advisory"], bool)
    assert out["balance"]["verdict"]


def test_structured_debrief_none_without_trace():
    assert build_structured_debrief({"setup": {"snapshot": {}}}) is None


# --- build_brain_followup ---------------------------------------------------
def test_brain_followup_from_inline_trace(monkeypatch):
    monkeypatch.setenv(_ENABLE, "1")
    out = build_brain_followup(_corner_archive() | {"gripCeilingG": 2.5})
    assert out is not None
    assert out["event"] == "coaching_response"
    assert out["debriefSource"] == "brain"
    assert out["cornerAnalysis"]
    assert "balance" in out


def test_brain_followup_from_archive_path(tmp_path, monkeypatch):
    monkeypatch.setenv(_ENABLE, "1")
    laps = tmp_path / "journal" / "laps"
    laps.mkdir(parents=True)
    archive_file = laps / "lap_test123.json"
    archive_file.write_text(json.dumps(_corner_archive()), encoding="utf-8")
    out = build_brain_followup(
        {"event": "lap_complete", "lap": 3, "archivePath": str(archive_file), "gripCeilingG": 2.5}
    )
    assert out is not None
    assert out["debriefSource"] == "brain"


def test_brain_followup_none_for_corner_table_only(monkeypatch):
    monkeypatch.setenv(_ENABLE, "1")
    # the live lap_complete payload (no trace, no archivePath) -> fall back to rules
    inbound = {"event": "lap_complete", "lap": 3, "telemetry": {"corners": [{"label": "T1"}]}}
    assert build_brain_followup(inbound) is None


def test_brain_followup_rejects_unsafe_archive_path(tmp_path, monkeypatch):
    monkeypatch.setenv(_ENABLE, "1")
    # a real file, but not under journal/laps/lap_*.json -> rejected by the safe-path guard
    bad = tmp_path / "passwd.json"
    bad.write_text(json.dumps(_corner_archive()), encoding="utf-8")
    assert build_brain_followup({"archivePath": str(bad)}) is None


def test_brain_followup_disabled_when_feature_off(monkeypatch):
    monkeypatch.delenv(_ENABLE, raising=False)
    assert build_brain_followup(_corner_archive()) is None
