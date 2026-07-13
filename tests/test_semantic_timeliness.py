"""Semantic-timeliness metric tests (#522) — synthetic tap, no hardware."""

import json

from tools.ai_sidecar.voice.semantic_timeliness import analyze


def _write_tap(path, rows):
    with open(path, "w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r) + "\n")


def _ticks(t0, seconds, spline0, spline1, speed, brake_at=None):
    """20 Hz ticks moving linearly spline0->spline1; optional brake onset time offset."""
    rows = []
    n = int(seconds * 20)
    for i in range(n + 1):
        f = i / n
        t = t0 + f * seconds * 1000.0
        brake = 0.0
        if brake_at is not None and t >= t0 + brake_at * 1000.0:
            brake = 0.8
        rows.append(
            {
                "t": t,
                "k": "tick",
                "spline": spline0 + f * (spline1 - spline0),
                "speed": speed,
                "brake": brake,
            }
        )
    return rows


def test_actionable_cue_and_coverage(tmp_path):
    t0 = 1_000_000.0
    # car covers spline 0.40->0.48 over 8 s at 90 km/h (25 m/s -> 200 m on a 2500 m track)
    rows = _ticks(t0, 8.0, 0.40, 0.48, 90.0, brake_at=6.0)
    mark = 0.46  # brake point ~150 m ahead of start
    rows.append(
        {
            "t": t0 + 1000.0,
            "k": "coaching.cue",
            "payload": {"kind": "late_brake", "urgency": "prepare", "spline": mark},
        }
    )
    rows.append(
        {
            "t": t0 + 1000.0,
            "k": "coaching.voice",
            "payload": {
                "seq": 1,
                "clip_id": "late_brake.prepare.calm.t01",
                "kind": "late_brake",
                "urgency": "prepare",
                "register": "calm",
                "duration_ms": 1200,
                "t_wall_ms": t0 + 1000.0,
            },
        }
    )
    tap = tmp_path / "tap.jsonl"
    _write_tap(tap, rows)
    report = analyze(tap, track_length_m=2500.0, audio_latency_s=0.1)
    assert report.summary.get("ACTIONABLE") == 1
    assert report.brake_events == 1 and report.brake_events_coached == 1
    assert all(report.assertions.values()), report.assertions


def test_after_fact_cue_fails_assertions(tmp_path):
    t0 = 2_000_000.0
    rows = _ticks(t0, 8.0, 0.40, 0.48, 90.0)
    mark = 0.405  # mark far behind the car by the time the cue sounds
    rows.append(
        {
            "t": t0 + 5000.0,
            "k": "coaching.cue",
            "payload": {"kind": "late_brake", "urgency": "act", "spline": mark},
        }
    )
    rows.append(
        {
            "t": t0 + 5000.0,
            "k": "coaching.voice",
            "payload": {
                "seq": 1,
                "clip_id": "late_brake.act.urgent.generic",
                "kind": "late_brake",
                "urgency": "act",
                "register": "urgent",
                "duration_ms": 380,
                "t_wall_ms": t0 + 5000.0,
            },
        }
    )
    tap = tmp_path / "tap.jsonl"
    _write_tap(tap, rows)
    report = analyze(tap, track_length_m=2500.0)
    assert report.summary.get("AFTER_FACT") == 1
    assert report.assertions["no_after_fact_brake_cues"] is False


def test_empty_tap_fails_evidence_assertion(tmp_path):
    """#523 review (Codex P2): an empty/no-voice tap proves nothing and must FAIL the gate."""
    tap = tmp_path / "tap.jsonl"
    _write_tap(tap, _ticks(1_000.0, 2.0, 0.1, 0.12, 80.0))  # a few ticks, zero cues
    report = analyze(tap, track_length_m=2500.0)
    assert report.assertions["evidence_present"] is False


def _brake_mark_cue(t, mark, corner=None, urgency="prepare"):
    """A ``coaching.cue`` (advisory) + matching ``coaching.voice`` (dispatch) pair for a mark."""
    cue = {
        "t": t,
        "k": "coaching.cue",
        "payload": {"kind": "late_brake", "urgency": urgency, "spline": mark},
    }
    voice = {
        "t": t,
        "k": "coaching.voice",
        "payload": {
            "seq": int(t) % 100000,
            "clip_id": f"late_brake.{urgency}.calm.t{corner or 0}",
            "kind": "late_brake",
            "urgency": urgency,
            "register": "calm",
            "duration_ms": 1200,
            "t_wall_ms": t,
        },
    }
    if corner is not None:
        cue["payload"]["corner"] = corner
        voice["payload"]["corner"] = corner
    return cue, voice


def _brake_onset(rows, t0, mark, span=(0.20, 0.80), seconds=24.0):
    """Set a sustained brake onset on the tick whose spline first reaches ``mark``."""
    onset_t = (mark - span[0]) / (span[1] - span[0]) * seconds
    for r in rows:
        rel = (r["t"] - t0) / 1000.0
        if onset_t <= rel <= onset_t + 0.8:
            r["brake"] = 0.8
    return t0 + (onset_t - 3.0) * 1000.0  # a plausible ~3 s-ahead cue time for this mark


def test_no_brake_marks_but_onsets_fails_gate(tmp_path):
    """#527 codex P1: brake onsets with NO late_brake advisory marks must NOT pass vacuously —
    that is a coaching pipeline emitting zero brake marks, not evidence of coverage."""
    t0 = 6_000_000.0
    rows = _ticks(t0, 24.0, 0.20, 0.80, 90.0)
    _brake_onset(rows, t0, 0.35)
    _brake_onset(rows, t0, 0.55)
    # only a non-brake cue is present, so evidence_present is satisfied but there are no marks.
    rows.append(
        {
            "t": t0 + 2000.0,
            "k": "coaching.cue",
            "payload": {"kind": "apex_deficit", "urgency": "info", "spline": 0.4},
        }
    )
    rows.append(
        {
            "t": t0 + 2000.0,
            "k": "coaching.voice",
            "payload": {
                "seq": 1,
                "clip_id": "apex_deficit.info.calm.t01",
                "kind": "apex_deficit",
                "urgency": "info",
                "register": "calm",
                "duration_ms": 900,
                "t_wall_ms": t0,
            },
        }
    )
    tap = tmp_path / "tap.jsonl"
    _write_tap(tap, rows)
    report = analyze(tap, track_length_m=2500.0)
    assert report.brake_events >= 2 and report.zones_crossed == 0
    assert report.assertions["brake_events_coached"] is False


def test_cue_for_one_zone_does_not_cover_another(tmp_path):
    """#527 codex P1: a cue must credit only its own mark/pass. Zone A cued+braked (coached);
    zone B braked but its heads-up was dropped — A's cue must NOT make B look coached."""
    t0 = 7_000_000.0
    rows = _ticks(t0, 24.0, 0.20, 0.80, 90.0)
    # Zone A: mark 0.35, braked, WITH an actionable cue (advisory + voice).
    a_cue_t = _brake_onset(rows, t0, 0.35)
    cue_a, voice_a = _brake_mark_cue(a_cue_t, 0.35, corner=1)
    rows.extend([cue_a, voice_a])
    # Zone B: mark 0.55, braked, advisory ONLY (dropped dispatch — no voice).
    b_cue_t = _brake_onset(rows, t0, 0.55)
    rows.append(
        {
            "t": b_cue_t,
            "k": "coaching.cue",
            "payload": {"kind": "late_brake", "urgency": "prepare", "spline": 0.55, "corner": 2},
        }
    )
    tap = tmp_path / "tap.jsonl"
    _write_tap(tap, rows)
    report = analyze(tap, track_length_m=2500.0, audio_latency_s=0.1)
    assert report.coachable_brake_zones == 2  # both zones braked in
    assert report.coachable_brake_zones_coached == 1  # only A drew a cue; B not covered by A's cue
    assert report.zones_crossed == 2 and report.zones_cued == 1
    assert report.assertions["brake_events_coached"] is False


def test_off_zone_onset_excluded_from_gate(tmp_path):
    """#527: a brake onset with no reference mark within 50 m is off-zone — it must NOT drag the
    coverage gate red. Two zones cued & braked in-window (coached) + one far-off correction dab."""
    t0 = 4_000_000.0
    # 0.20 -> 0.80 over 24 s at 90 km/h (25 m/s) on a 2500 m track = the whole lap.
    rows = _ticks(t0, 24.0, 0.20, 0.80, 90.0)
    # Two real brake zones the driver brakes in, each with a mark + cue ~3 s ahead.
    for i, mark in enumerate((0.35, 0.55)):
        # brake onset AT the mark: spline s=mark -> f=(mark-0.20)/0.60 -> t offset.
        onset_t = (mark - 0.20) / 0.60 * 24.0
        for r in rows:
            if r["t"] >= t0 + onset_t * 1000.0:
                r["brake"] = 0.8
                break
        # sustain the brake for the zone
        for r in rows:
            if t0 + onset_t * 1000.0 <= r["t"] <= t0 + onset_t * 1000.0 + 800.0:
                r["brake"] = 0.8
        cue, voice = _brake_mark_cue(t0 + (onset_t - 3.0) * 1000.0, mark, corner=i + 1)
        rows.extend([cue, voice])
    # An off-zone correction dab at spline ~0.70 — nearest mark 0.55 is 0.15*2500 = 375 m away.
    for r in rows:
        if r["t"] >= t0 + ((0.70 - 0.20) / 0.60 * 24.0) * 1000.0:
            r["brake"] = 0.8
            break
    tap = tmp_path / "tap.jsonl"
    _write_tap(tap, rows)
    report = analyze(tap, track_length_m=2500.0, audio_latency_s=0.1)
    # 3 raw onsets, 1 off-zone → 2 coachable zones, both coached → gate green.
    assert report.brake_events == 3
    assert report.off_zone_brake_onsets == 1
    assert report.coachable_brake_zones == 2
    assert report.coachable_brake_zones_coached == 2
    assert report.assertions["brake_events_coached"] is True
    assert report.zones_crossed == 2 and report.zones_cued == 2


def test_repeat_onsets_in_one_zone_count_once(tmp_path):
    """#527: several stab-and-release dabs inside ONE cued zone collapse to a single coachable
    zone, so a scrappy driver does not inflate the denominator."""
    t0 = 5_000_000.0
    rows = _ticks(t0, 12.0, 0.30, 0.60, 90.0)
    mark = 0.42
    onset_t = (mark - 0.30) / 0.30 * 12.0  # seconds into the run where the car reaches the mark
    # Four brake dabs clustered around the mark (all within 50 m at 25 m/s: ~2 m/tick).
    dab_ts = [onset_t - 0.3, onset_t + 0.1, onset_t + 0.4, onset_t + 0.7]
    for dab in dab_ts:
        released = False
        for r in rows:
            rel_t = (r["t"] - t0) / 1000.0
            if dab <= rel_t <= dab + 0.15:
                r["brake"] = 0.8
                released = True
            elif released and rel_t > dab + 0.15:
                break
    cue, voice = _brake_mark_cue(t0 + (onset_t - 3.0) * 1000.0, mark, corner=4)
    rows.extend([cue, voice])
    tap = tmp_path / "tap.jsonl"
    _write_tap(tap, rows)
    report = analyze(tap, track_length_m=2500.0, audio_latency_s=0.1)
    assert report.brake_events >= 2  # several raw onsets
    assert report.coachable_brake_zones == 1  # collapsed to one zone
    assert report.coachable_brake_zones_coached == 1
    assert report.assertions["brake_events_coached"] is True


def test_just_late_act_cue_is_too_late_not_redundant(tmp_path):
    """#523 review (Codex P2): timing verdicts precede REDUNDANT — a late act cue with the
    pedal already down must fail the gate as TOO_LATE, not hide as (non-gating) REDUNDANT."""
    t0 = 3_000_000.0
    rows = _ticks(t0, 8.0, 0.40, 0.48, 90.0, brake_at=1.0)  # braking from early on
    mark = 0.425  # heard-complete lands just ~0.35 s before the mark -> TOO_LATE territory
    rows.append(
        {
            "t": t0 + 1500.0,
            "k": "coaching.cue",
            "payload": {"kind": "late_brake", "urgency": "act", "spline": mark},
        }
    )
    rows.append(
        {
            "t": t0 + 1500.0,
            "k": "coaching.voice",
            "payload": {
                "seq": 1,
                "clip_id": "late_brake.act.urgent.generic",
                "kind": "late_brake",
                "urgency": "act",
                "register": "urgent",
                "duration_ms": 380,
                "t_wall_ms": t0 + 1500.0,
            },
        }
    )
    tap = tmp_path / "tap.jsonl"
    _write_tap(tap, rows)
    report = analyze(tap, track_length_m=2500.0)
    brake = [c for c in report.cues if c.kind == "late_brake"][0]
    assert brake.verdict == "TOO_LATE", (brake.verdict, brake.tta_s, brake.brake)
    assert report.assertions["no_too_late_brake_cues"] is False
