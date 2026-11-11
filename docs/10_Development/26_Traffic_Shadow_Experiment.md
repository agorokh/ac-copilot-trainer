# Traffic shadow experiment (#955)

This is the bounded `REX-20261111-01` experiment, capped at two engineering days
and 90 minutes of replay/shadow capture. No driving actuation is included.
The frozen native-replay experiment failed the accuracy bar on 2026-11-11.
The decision is **no-go for live cue activation**; thresholds were not tuned after
the failure. The shadow collector remains off by default. See the results below.

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
The sidecar validates the bounded scalar roster at ingress. Only observer peers
receive the raw roster; screen, browser, haptics and physical peers receive their
existing scalar tick without traffic fields, preserving peripheral buffer limits.

New captures also retain these raw observations in the native lap archive's
`traffic.frames`, streamed through the existing asynchronous archive writer.
The first partial lap after arming is incomplete. Collection is bounded at 12,000
snapshots per lap; overflow marks the lap incomplete. Raw archives are not edited.
Readers recompute occupancy and check completeness, monotonic observation-clock
coverage and <=250 ms gaps. The simulation lap duration is validated separately;
it is never compared to the observation-clock span. Known constrained, unknown,
malformed, or incomplete captures cannot
enter human progression, live reference, reference comparison, or plant fitting.
Explicit traffic denials are managed restrictions even without an attribution
envelope, so existing managed-only consumers enforce them. Analysis stays readable.
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

## Frozen experiment result (2026-11-11)

The operator authorized autonomous input discovery. Recursive local inventory
found five multi-car recordings; native CSP replay playback captured all five.
A public [54-car Le Mans recording](https://www.overtake.gg/threads/le-mans-series-friday-night-events-with-assetto-corsa.205988/page-2)
supplied an additional five minutes of observation. Six sealed captures contain
23,506 complete scalar rosters with zero sampling errors. No driving, session-start,
setup or live voice actuation was performed. Original replays remain hash-bound
and private. The temporary recorder and track junction were retired; the original
trainer junction, app selection and ten affected configuration/state files were
hash-restored, including one archive removed by ordinary trainer retention during
the first replay attempt. Both the pre-capture and post-capture states are retained.

The [frozen fixture](../../tests/fixtures/traffic_shadow_955/frozen_45.json) has SHA256
`c3ee67ae90a85f3bcff53c05bf6120c1635fae7cb77dd349d7ff1fa3dcd4869c`.
It was sealed before predictions, against candidate `cf93d9681ab93f7fe3336d395822537877e21982`.
Labels came from observed trajectory panels around the existing canonical corner
segmenter's deceleration entries, without importing the candidate evaluator.
This is a single unblinded agent's exploratory labeling, with correlated laps.
All five natural controls cover adjacent track segments; pit, disconnected and
wrap cases have synthetic coverage only. These limits prevent a broad safety claim.

| Frozen cohort | Required | Candidate | Solo policy | Blanket multi-car mute |
| --- | --- | --- | --- | --- |
| Occupied approaches suppressed | >=19/20 | **18/20: Fail** | 0/20 | 20/20 |
| Clear approaches retained | >=16/20 | 20/20 | 20/20 | 0/20 |
| Adjacent-track controls retained | 5/5 | 5/5 | 5/5 | 0/5 |

The two misses are A011 and A012. Car 1 was 123.42/86.88 m away, respectively,
on the same observed approach; its height differed by 4.54/3.49 m. The absolute
3 m height gate excluded it on those elevation-changing sections. Their original
labels and observations remain unchanged in the fixture. The issue's calibration
stop rule applies: no threshold
search or live promotion follows this failed split. The candidate beats blanket
muting on clear retention, but does not meet the necessary occupied-approach bar.
The [evaluation JSON](../../tests/fixtures/traffic_shadow_955/evaluation.json)
retains every prediction, the two comparators and the negative controls.

Across the same 45 contexts, 135 separately identified perturbations (>250 ms,
missing position, invalid index) returned unknown. All 135 also suppressed PRIME
cues through the actual coaching consumer in explicit offline replay mode. Two
native Nurburgring wrap-to-wrap intervals, with 2,138 and 2,019 unmodified traffic
frames, passed through the real Lua asynchronous writer and were read back from
disk. Their aggregate statuses were constrained and eligible respectively.
Both separately marked incomplete variants were unknown. Analysis allowed all
four; zero constrained/unknown variants entered human_progression, live_reference
or plant_fit. The eligible interval kept its existing legacy provenance verdict;
it was not certified human-driven. The minimal player traces used for this writer
probe were derived from capture observations, not native trainer-app lap records.
Their lap durations use replay-frame simulation time; traffic timestamps retain
the distinct producer observation clock. Coverage never assumes these clocks run
at the same rate. Partial traffic chunks flush through the existing writer and
propagate flush failures before resuming the asynchronous job.
[Consumer checks](../../tests/fixtures/traffic_shadow_955/consumer_checks.json)
retain the methods, source intervals, output hashes and qualification verdicts.

Actual CSP 0.3.1/4302 timing is retained in the
[native timing ledger](../../tests/fixtures/traffic_shadow_955/native_timings.json).
The 54-car loop measured p99 1.4834/1.9961 ms at 10/20 Hz, exceeding the budget
at that larger roster. A timing-only loop over 20 actual CSP cars inside that
same replay measured p99 0.5677/0.5629 ms (2,656/5,311 samples). It never replaced
the complete 54-car eligibility roster. This supports the cost of the 20-car
iteration, but **does not establish the literal 20-car-grid clause**. No 20-car
grid was captured; that clause remains unverified. The 8/11/16-car measurements
and the LuaJIT mock benchmark are recorded separately. Opponent data are scalar;
the regression suite traps any wheel access and confirms zero wheel reads.

To reproduce the frozen accuracy counts from the repository root:

```python
import hashlib
import json
from pathlib import Path
from tools.ai_sidecar.traffic_eligibility import traffic_eligibility

path = Path("tests/fixtures/traffic_shadow_955/frozen_45.json")
assert hashlib.sha256(path.read_bytes()).hexdigest() == (
    "c3ee67ae90a85f3bcff53c05bf6120c1635fae7cb77dd349d7ff1fa3dcd4869c"  # pragma: allowlist secret (fixture SHA256)
)
cases = json.loads(path.read_text())["approaches"]
for cohort in ("constrained", "clear", "adversarial"):
    selected = [c for c in cases if c["cohort"] == cohort]
    correct = sum(traffic_eligibility(c["row"]["traffic"],
        now_s=c["row"]["traffic_now_s"]).status == c["label"] for c in selected)
    print(cohort, correct, len(selected))
```
