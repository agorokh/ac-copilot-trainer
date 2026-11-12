# Traffic shadow experiment (#955)

This is the bounded `REX-20261111-01` experiment, capped at two engineering days
and 90 minutes of replay/shadow capture. No driving actuation is included.
The first frozen native-replay experiment failed the accuracy bar on 2026-11-11.
An operator-authorized second iteration corrected elevation handling and sampler
cadence, then passed a fresh frozen split and actual native 20-car timing.
The shadow collector remains off by default. These exploratory results do not
authorize live cue activation. Both iterations and their limits are retained below.

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

## First frozen experiment result (2026-11-11, historical)

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

## Second iteration (2026-11-11)

The operator explicitly authorized fixing A011/A012, a fresh frozen set and real
20-car verification. World-height differences now receive an allowance tied to
along-track separation: `abs(gap) + 3 m`. Both spline and 3D proximity gates remain.
This corrects ordinary road elevation without replacing the gate with an arbitrary
larger fixed height cap. It is still a provisional scalar approximation of road
topology. A nearby overpass with insufficient along-track separation stays clear.
The sampling deadline now preserves phase across render-frame jitter and skips
missed deadlines without manufacturing catch-up observations. Both changes have
focused regressions, including the two exact original misses.

Input discovery found a [documented native version-16 replay writer](https://github.com/mishan/assetto-ts/blob/main/packages/acreplay/src/acreplay.ts).
Its standings layout matched all 35 snapshots in the public 54-car recording.
A private derived replay retains 20 original native car blocks byte for byte,
filters/remaps their standings entries, and omits optional CSP extension data.
The original recording is unchanged. The retained roster is ego plus its 19 most
frequent 3D neighbors within 150 m over previously unused source frames 5000–15000;
selection did not import or run the candidate predictor. This deliberately enriches
traffic and does not estimate ordinary race prevalence. AC loaded an actual
20-car world; every captured native `sim.carsCount` was 20 and every unmodified
`ac.getCar(i)` index was checked. This is a derived native replay of recorded
trajectories, not an original 20-car race or a timing-only subset in a 54-car world.

The fresh [45-case fixture](../../tests/fixtures/traffic_shadow_955/iteration2_frozen_45.json)
was frozen and [hash-published before scoring](https://github.com/agorokh/ac-copilot-trainer/issues/955#issuecomment-6815408085).
SHA256: `a473634d25aee2e929691daa39c64f2d7b886d2a182253d29000e31fe5f7177d`.
Candidate `0769c3d` was fixed before capture. Labels describe current occupancy of
the existing current-speed, two-second roadway region capped at 150 m, measured
along observed 3D roadway geometry independently of the candidate's normalized
spline, Euclidean shortcut and height test. Recorded future player motion supplies
road geometry; it does not redefine the region as distance traveled during future
braking. These are regional occupancy labels, not collision predictions or proof
that traffic causally impeded the driver.

The first blind Council image audit rejected unmarked overlapping paths as
future-interference evidence. Timed markers and the explicit current road region
were added. A subsequent 24-case blind geometric audit agreed on 12 occupied and
8 empty cases and flagged four uncertain cases. All four were excluded before
predictions, with later chronological occupied cases filling the cohort. Only
one of the two requested voices completed that second audit; no quorum is claimed.
The root agent remains a single unblinded primary labeler who knew the candidate
design. Laps and corners are correlated. Five natural pit controls span four
passages through one pit complex, including two keyframes with different nearest
pit vehicles from one passage. They are five actual contexts, not five independent
safety events. Pit controls, source indices and exclusion reasons are in the fixture.

| Fresh cohort | Required | Candidate | Solo policy | Blanket multi-car mute |
| --- | --- | --- | --- | --- |
| Occupied approaches suppressed | >=19/20 | 20/20 | 0/20 | 20/20 |
| Clear approaches retained | >=16/20 | 20/20 | 20/20 | 0/20 |
| Native pit contexts retained | 5/5 | 5/5 | 5/5 | 0/5 |

[Evaluation JSON](../../tests/fixtures/traffic_shadow_955/iteration2_evaluation.json)
retains every prediction. The unchanged original fixture is now regression data:
20/20 occupied, 19/20 clear and 5/5 adjacent controls. A035 is a new conservative
false suppression (97.96 m world distance, 98.51 m spline gap and 6.73 m height
difference); its eligible label is preserved. No labels or thresholds changed
after the fresh score.

The [native timing ledger](../../tests/fixtures/traffic_shadow_955/iteration2_native_timings.json)
binds source/derived replay hashes, all 20 retained car-block hashes, module and
recorder hashes, phase histograms and 22,203 complete, error-free native rosters.
The per-call timer includes production `traffic_context:update` and its frame
retention, excluding the temporary JSON writer. Opponent fields remain scalar;
the wheel-access trap regression still verifies zero wheel reads.

| Actual native grid | Configured rate | Samples | Achieved rate | p99 step | Maximum step |
| --- | --- | --- | --- | --- | --- |
| 20 cars | 10 Hz | 1,800 | 9.99976 Hz | 0.5583 ms | 0.8752 ms |
| 20 cars | 20 Hz | 20,403 | 19.99996 Hz | 0.7034 ms | 2.8739 ms |

Both p99 results satisfy the <=1 ms criterion; the maximum is reported separately
and is not asserted to satisfy it. Maximum observation gaps were 116.1/68.5 ms.
The replay source records at 120 ms intervals; CSP interpolates the native state
between recorded frames. This is observed CSP 0.3.1/4302 cost, not a qualification
of every supported CSP version or live transport age. Twenty car-block hashes
matched exactly. A separate 5,820-point audit measured at most 0.468 m distance
from the original recorded local 3D polyline; it does not claim centimetre identity
between interpolated native positions and source frame positions.

All 135 fresh stale/missing/index perturbations returned unknown and silenced
PRIME cues through the real coaching runtime's explicit offline replay seam.
Five native 20-car wrap-to-wrap intervals passed through the real asynchronous
Lua archive writer and were read back from disk. They were constrained; separately
identified incomplete variants were unknown. Analysis remained readable and zero
constrained/unknown variants entered human_progression, live_reference or plant_fit.
[Consumer evidence](../../tests/fixtures/traffic_shadow_955/iteration2_consumer_checks.json)
retains the intervals, archive hashes and qualification verdicts. The player
traces for this writer probe are minimal derived traces, not native trainer-app
lap archives or human-driving certification. A separate native solo replay retains
the original ego car block unchanged and contains no opponents. Its full
wrap-to-wrap interval (4,163 frames) was eligible after the same writer/readback
path; its incomplete variant was unknown. The clean interval kept the existing
`legacy_unknown` allowance for all four uses, rather than receiving human-source
certification. Its 5,521 native observations are positive-control evidence only,
not part of the 20-car cost proof or fresh accuracy split.

Both owned replay sessions were closed and their temporary collectors/track links
retired. Seven affected configuration/state files per session were restored;
all 405/406 original file hashes matched their respective pre-capture snapshots.
The original trainer junction was restored and the canonical rig lock released.
Pre-existing Game Point, Steam and SimHub remained running. Conservative capture
accounting, including all owned setup/restoration windows and prior failed setup,
is 78.99 minutes across both iterations, within the original 90-minute cap.

To reproduce the fresh result, use the code above with the second fixture path
and its recorded SHA256. The first fixture's bytes and historical failed result
remain unchanged. No driving, race start, setup, live voice or firmware actuation
is part of either iteration.
