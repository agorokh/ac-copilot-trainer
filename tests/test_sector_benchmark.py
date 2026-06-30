from __future__ import annotations

import pytest

from tools.ai_sidecar.lap_dynamics import LapTrace
from tools.ai_sidecar.sector_benchmark import (
    build_sector_delta_report,
    build_sector_map,
    build_superlap,
    segment_duration_s,
)


def _lap_from_micro_durations(durations: list[float], *, car: str = "car", track: str = "track"):
    spline = [i / len(durations) for i in range(len(durations) + 1)]
    t_s = [0.0]
    for duration in durations:
        t_s.append(t_s[-1] + duration)
    n = len(spline)
    return LapTrace(
        spline=spline,
        t_s=t_s,
        v_ms=[40.0] * n,
        brake=[0.0] * n,
        throttle=[1.0] * n,
        steer=[0.0] * n,
        gear=[4.0] * n,
        x=[float(i) for i in range(n)],
        z=[0.0] * n,
        lap_ms=t_s[-1] * 1000.0,
        car_id=car,
        track_id=track,
    )


def test_sector_map_defaults_to_three_by_three_micro_sectors() -> None:
    smap = build_sector_map()
    assert [s.label for s in smap.sectors] == ["S1", "S2", "S3"]
    assert [m.label for m in smap.micro_sectors[:4]] == ["S1.1", "S1.2", "S1.3", "S2.1"]
    assert smap.micro_sectors[-1].label == "S3.3"


def test_sector_delta_report_localizes_micro_sector_loss_and_gain() -> None:
    reference = _lap_from_micro_durations([10.0] * 9)
    candidate = _lap_from_micro_durations([10.0, 12.0, 10.0, 9.0, 10.0, 10.0, 10.0, 10.0, 10.0])

    report = build_sector_delta_report(candidate, reference)

    assert report.total_delta_s == pytest.approx(1.0)
    assert report.sectors[0].label == "S1"
    assert report.sectors[0].delta_s == pytest.approx(2.0)
    assert report.sectors[1].delta_s == pytest.approx(-1.0)
    deltas = {seg.label: seg.delta_s for seg in report.micro_sectors}
    assert deltas["S1.2"] == pytest.approx(2.0)
    assert deltas["S2.1"] == pytest.approx(-1.0)


def test_superlap_stitches_fastest_micro_sectors() -> None:
    steady = _lap_from_micro_durations([10.0] * 9)
    spiky = _lap_from_micro_durations([12.0, 12.0, 8.0, 12.0, 12.0, 12.0, 12.0, 12.0, 12.0])

    superlap = build_superlap([steady, spiky])

    assert superlap is not None
    assert superlap.lap_time_s == pytest.approx(88.0)
    assert superlap.baseline_best_lap_s == pytest.approx(90.0)
    assert superlap.gain_vs_best_s == pytest.approx(2.0)
    assert {seg.label: seg.source_index for seg in superlap.segments}["S1.3"] == 1


def test_segment_duration_requires_sampled_window_edges() -> None:
    lap = _lap_from_micro_durations([10.0] * 9)
    sparse = LapTrace(
        spline=lap.spline[1:],
        t_s=lap.t_s[1:],
        v_ms=lap.v_ms[1:],
        brake=lap.brake[1:],
        throttle=lap.throttle[1:],
        steer=lap.steer[1:],
        gear=lap.gear[1:],
        x=lap.x[1:],
        z=lap.z[1:],
        lap_ms=lap.lap_ms,
        car_id=lap.car_id,
        track_id=lap.track_id,
    )

    assert segment_duration_s(sparse, build_sector_map().micro_sectors[0]) is None


def test_superlap_requires_complete_micro_sector_coverage() -> None:
    lap = _lap_from_micro_durations([10.0] * 9)
    sparse = LapTrace(
        spline=lap.spline[1:],
        t_s=lap.t_s[1:],
        v_ms=lap.v_ms[1:],
        brake=lap.brake[1:],
        throttle=lap.throttle[1:],
        steer=lap.steer[1:],
        gear=lap.gear[1:],
        x=lap.x[1:],
        z=lap.z[1:],
        lap_ms=lap.lap_ms,
        car_id=lap.car_id,
        track_id=lap.track_id,
    )

    assert build_superlap([sparse]) is None
