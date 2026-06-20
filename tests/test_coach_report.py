"""Tests for the coaching debrief renderer + CLI (tools.ai_sidecar.coach_report)."""

from __future__ import annotations

import json
import math

from tools.ai_sidecar.coach_report import build_debrief, main


def _corner_archive(*, degrade: float = 0.0) -> dict:
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
        "car": {"id": "ks_porsche_911_gt3_r_2016"},
        "track": {"id": "magione", "lengthM": total},
        "lap": {"lap_ms": int(t_ms[-1]), "is_valid": True},
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


def test_build_debrief_renders_sections():
    text = build_debrief(_corner_archive(), grip_ceiling_g=2.5)
    assert "Coaching debrief" in text
    assert "Setup at a glance" in text
    assert "Brake bias (front): 66" in text
    assert "Balance (aero vs mechanical)" in text
    assert "Per-corner" in text


def test_build_debrief_with_reference_shows_time_loss():
    ref = _corner_archive(degrade=0.0)
    student = _corner_archive(degrade=8.0)  # student carries less apex speed
    text = build_debrief(student, reference_archive=ref, grip_ceiling_g=2.5)
    assert "vs reference" in text or "losing time" in text


def test_cli_main_runs(tmp_path, capsys):
    p = tmp_path / "lap.json"
    p.write_text(json.dumps(_corner_archive()), encoding="utf-8")
    rc = main([str(p), "--grip-ceiling-g", "2.5"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "Coaching debrief" in out
