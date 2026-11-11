# Traffic shadow experiment (#955)

This is the bounded `REX-20261111-01` experiment, capped at two engineering days
and 90 minutes of replay/shadow capture. No driving actuation is included.
Accuracy and CSP timing remain unverified until the issue's real capture passes.

The trainer's session-only `config.set` key `trafficShadowEnabled=true` arms
20 Hz scalar collection through the existing authenticated harness protocol.
The default is false. Setting it false or resetting/reloading the session clears
the collector. It never enables live cue suppression. No firmware flash is needed.

`telemetry_tick.payload.traffic` contains schema version 1, a zero-based complete
car roster, `cars_count`, `track_length_m`, and `sampled_at_s`. Each car has
`index`, XYZ position in metres, normalized spline in [0,1), speed in km/h,
and boolean connected/pit-lane flags. No opponent wheels are read or serialized.
`traffic_now_s` is sampled on the SAME script clock at publication. This measures
producer-local sampling age; it does not certify network residence time.

New captures also retain these raw observations in the native lap archive's
`traffic.frames`, streamed through the existing asynchronous archive writer.
The first partial lap after arming is incomplete. Collection is bounded at 12,000
snapshots per lap; overflow marks the lap incomplete. Raw archives are not edited.
Readers recompute occupancy and check monotonic coverage, <=250 ms gaps, and lap
duration. Known constrained, unknown, malformed, or incomplete captures cannot
enter human progression, live reference, or plant fitting. Analysis stays readable.
Old archives without traffic remain unassessed under the existing provenance
policy; this experiment does not certify them as traffic-clean or human-driven.

`traffic_eligibility(context, now_s=...)` requires an observation-domain clock.
Stale (>250 ms), future, incomplete, nonfinite, or malformed observations return
`unknown`. The provisional geometry gate combines wrapped spline distance and
3D world separation, excludes disconnected/pit cars only after field validation,
and checks vertical separation. Its thresholds have not been replay-calibrated.

`build_coach_runtime(..., traffic_gate_mode="replay")` is an explicit offline
seam: it suppresses solo PRIME cues and prevents contaminated corner passes from
updating the coaching ledger. A constrained/unknown approach stays contaminated
through that pass, even if the exit is clear. Emergency SAVE cues remain available.
The default `shadow` mode only computes diagnostics. Telemetry cannot arm replay
enforcement. Live activation needs a separate decision and transport freshness proof.

Run `python -m pytest -q tests/test_traffic_eligibility.py tests/test_lap_archive_async.py`.
The existing replay harness exposes `benchmark_traffic_sampling(hz=10)` and
`benchmark_traffic_sampling(hz=20)`: these run the real collector under LuaJIT 2.1
with schema-gated mock fields and return timings plus a histogram. They do not
prove CSP C-struct or render-frame cost.

Before tuning, freeze and hash 45 independently replay-labeled approaches:
20 constrained, 20 clear, and five adversarial controls. Compare the same inputs
against the current solo policy and blanket multi-car muting. Require >=19/20
constrained suppression, >=16/20 clear retention, all five controls correct, and
<=1.0 ms CSP p99 at 20 cars / both sampling rates. Fewer than 40 valid captured
multi-car approaches means Inconclusive. Synthetic tests never fill this corpus.
