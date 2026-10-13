---
type: investigation
status: active
created: 2026-10-13
updated: 2026-10-13
memory_tier: canonical
issue: https://github.com/agorokh/ac-copilot-trainer/issues/815
relates_to:
  - AcCopilotTrainer/03_Investigations/2026-10-13-071925Z-moza-provenance-channel-evidence-815-92f67c.md
  - AcCopilotTrainer/00_System/invariants/data-immutability.md
  - AcCopilotTrainer/00_System/handoffs/2026-10-13-135149Z-moza-part-a3-capture-815-d84bb7.md
---

# MOZA Part A3: observed AI lap captured; consumer qualification incomplete

The separately authorized Porsche/Spa run captured a complete native lap of **2:17.983** within the
observed MOZA AI-on interval. Native timing marks it valid. The new MOZA practice cache is directly
linked to MOZA's evaluation record, which explicitly labels it AI-intervened and ai-debug-only.
Its association with the native capture is supported by observed timing, combo and numeric agreement;
there is no shared native/MOZA session identifier. Consumer-specific qualification remains incomplete.
It does not qualify the four historical caches, a human technique reference, human progression,
plant fitting or a production AI speed frontier. No #815 acceptance checkbox is advanced.

The new archive also reproduces the provenance gap: it carries `source=in_game` and `is_pb=true`
despite the observed MOZA-assisted run. MOZA instead marks both laps ai-debug-only, with two observed/
complete laps, zero evaluated laps, and null best/latest eligible lap IDs. Native collection/PB labels
therefore do not establish human authority.
No driver-profile rebuild was performed or proved by this investigation.

## Attempt two: completed runtime capture

All times are UTC on 2026-10-13. Parent alone operated the UI; passive agents observed and retained
receipts. The secondary-window helper error was resolved by resetting node_repl and reimporting sky,
without a further user step. MOZA Launch was clicked at 16:13:54.177 for Spa / Porsche 911 GT3 R 2016;
Drive followed at 16:14:47.192. The passive observer began at 16:14:20.562, before Drive, with exact
native identity `ks_porsche_911_gt3_r_2016` / `spa` / empty layout.

At 16:16:28.015 read-only OpenFileMapping probes found all four bare/Local canonical Car0/CarControls0
sections absent in Windows session 1. No mapping was created or written. This sample excludes that
mechanism then, not every input source or a controller started later.

Parent enabled the master AI at 16:16:56.796 and confirmed orange On. Wheel, pedal and gear AI were
On; mode was Professional / Direct steering, Heavy force feedback and intervention level 1.0.
MOZA's header showed the exact combo Running. Parent's 16:17 screenshot showed the Porsche moving
at 232 km/h in fifth gear while those controls were On. These observations support MOZA involvement,
not a continuous sensor-level proof that no human/device override occurred.

| Native boundary | Time | Lap timing | Disposition |
|---|---|---|---|
| First | 16:19:17.601537 | 302,955 ms | Contains pre-activation stationary/partial history; excluded from clean full-AI-lap interpretation. |
| Second | 16:21:35.583692 | 137,983 ms; valid=true | Complete boundary-to-boundary interval 137.982155 s within the reported AI-on interval; captured candidate for qualification. |

Both belong to native session SHA-256
`ccfef7121c45e71d75520ac379c9f3e095285c7f0555edbf0da9961aae868c99`.
The second artifact is
`lap_20261013-162135_07e730bf_2_137983_6ace5a8f6182.json`, SHA-256
`097dac7f46a0290b8bd8319fc894b53558009a0ecda0990187bda69b2842ca46`.
Its lap UUID SHA-256 is
`0df70dadfe02d4ee8f20124f8ed0fbf35e3520fe8ccc1881b84583e2953f895d`.

The archive has 2,000 samples and recorded elapsed extent 137,959.0862 ms, 23.914 ms short of official
timing. Its only nonincreasing spline step is the final sample at index 1999: measured progression
reaches 0.999878883 then wraps to 0.000339427. All prior spline samples and the elapsed clock are
strictly increasing. No raw trace was repaired. A read-only call on the protected copy confirmed
the existing `track_map._valid_trace` accepts it as 1,999 samples through its in-memory measured
finish-wrap handling; `_reference_provenance_valid` also accepts its in_game format. The wrap is
therefore not a missing implementation or current MAP rejection. These gates do not establish
human control or protect human progression from the observed AI-origin archive.
Recorded conditions include ambient 26 C, weather type 16, Medium slick tyres and empty setup hash.
Parent's practice table also displayed air 26 C / road 37 C / Slick Medium / 30 L / TC Off / ABS On.
Keep UI-reported conditions distinct from independently measured or missing/defaulted values.

The passive observer failed after both boundaries when replacing observer-status.json raised
PermissionError WinError 5. Last committed status was 16:21:48.746860; a preserved temporary snapshot
was dated 16:21:50.757510. It did not finish cleanly and did not observe AI-off or AC exit continuously.
The cause is unproved. Subsequent UI and post-exit receipts independently cover those later actions;
do not bridge the observer gap. The narrow scratch-only persistence repair does not repair history.

Parent switched the master Off at 16:22:05.663 with grey readback, then gracefully closed AC with
Alt+F4 at 16:22:12.447. Its window was absent around 16:22:47. Minimize to Tray had been visibly
restored at 14:02, and Always on top On was restored with orange pin around 16:16:40. At
16:27:29.8473472, the separate cleanup receipt found zero named AC/Content Manager/Steam/webhelper/
SimHub/Game Point processes and zero port-8765 listeners. MOZA Racing Lab/Pit House were preserved.

## Data preservation and scope

Before runtime, 185 historical native archives / 523,733,170 bytes were copied to the separate
gitignored `.scratch/moza-qualification/part-a3-live/historical-backup/laps/` directory and verified
against original size and SHA-256. The attempt-two baseline reverified all 185 protective copies.
The 500 MiB cap left only 554,830 bytes of headroom; it was not raised.

Two oldest originals were subsequently absent from the live native directory after the two new
archives arrived, consistent with the existing retention policy. Their protected copies exist:
`lap_20260714-181022_19c16b3c_2_96624_6a567b8e2a26.json` and
`lap_20260714-181159_19c16b3c_3_96623_6a567bef84fd.json`.
The final 16:28:23 verification found all 185 protected historical copies byte-matched and all 183
remaining native originals unchanged. The 193-input baseline accounted for 190 unchanged, two rotated
native originals and one changed evaluation snapshot. Two new native files and two new MOZA caches
were captured stably; the full native lap and both caches also have verified raw-local copies.
Do not describe the live native directory as unchanged or these per-file checks as atomic. Preserve
the raw backup; it is not merely metadata and must not enter git.

At the boundary-two delta, no new MOZA view cache had arrived. Opening the normal record UI then
produced a 137.983-second practice cache (SHA-256 50650b484d11a1e64841de2fc2fa1d065f9bfa1b58cb6fc13a981d5946147173)
and a distinct 138.345-second comparison cache (SHA-256 7865f109943b92b4eb5a500a84b6073927ee4dda1df10356f4dbd0f383b0e218).
Parent saw practice lap 2 labelled Best result and AI intervention, and the separate AI Best source
labelled prerecorded AI reference. The practice cache lapId exactly equals evaluation id/recordUid
(identity SHA-256 468aa3a8889a996de7b0b9f60f039eb51676b1bd79ea09364a41f08ee7250082).
Evaluation explicitly records aiIntervened=true, eligibility=ai-debug-only, complete/finalized/valid=true.
That is direct MOZA-internal authority linkage, not a native-session-ID join or proof of exclusive control.

Exploratory held-out comparison of the practice cache with native lap 2 found speed MAE 0.0489 km/h,
position p95 error 0.349 m, clock residual p95 7.33 ms and 97.5% categorical gear equality. The fitted
MOZA/native steering slope was 1.24927 for this session, not a universal calibration. The comparison
excluded 448 cache nonforward samples and the one native finish wrap. Declared/detail counts,
boundary behavior, gear transitions and scaling remain limits; numerical agreement is not full
channel or production certification. Raw bytes were not normalized or rewritten.

## Attempt one: preserved negative result

The earlier attempt launched AC at 13:37:17.635 and entered Drive at 13:38:26.649, but Racing Lab kept
AI disabled with no compatible pedals/wheelbase warnings. Pit House 1.4.1.13 displayed R3/KS/SR-P.
A graceful Racing Lab restart showed Bundled H5 unavailable, then EPIPE in
BridgeProcessSupervisor._stopWatchdog on close; the installed shortcut stalled at automatic Pit
House sign-in. No common root cause or vendor regression was diagnosed, and no authentication
stores or credentials were inspected.

Escape at 13:47:23 and after focus did not pause AC. Parent closed AC at 13:51:05.534 and verified
its window gone at 13:51:13. Passive observation from 13:40:37 to 13:52:29 saw zero lap events;
last tick was 13:51:05.459. This attempt remains no AI/no lap, with no new native/cache artifacts.
Its rehash verified all 185 native originals, all 185 protective copies and four old caches.

The wider 13:53 check had 191/193 matches: resource-catalog.json was missing and the empty 222-byte
evaluation snapshot changed. At 13:56:17 the catalog returned with its original hash, yielding
192/193 matches across dated checks. Preserve both observations; this is not an atomic all-green
snapshot. Home recovered automatically around 13:56–13:57 without an authentication action;
compatible R3/SR-P devices were observed at 13:57. The 14:02 continuation then encountered the
separate UI-helper foreground-process error, later resolved before attempt two.
Earlier AC/Game Point/port-8765 cleanup proof applies only to attempt one, not the later launch.

## Consumer decision and remaining evidence

The measured candidate may support offline comparison or silent replay research after identity,
channels and timing are validated. A MOZA-controlled practice lap is distinct from the selected
UI-labelled AI Best comparison source. Keep both roles explicit. AI/shared/unknown input authority must
not be promoted to human PB/progression or human technique.

Current code explains the gap and the separate target gate: `lap_archive.lua:384` hardcodes
`in_game`; `driver_profile.py:314 _is_driver_lap` excludes imported/reference sources but does not
classify control authority. `track_map.py:340/386/428` supplies existing source-format, measured-trace
and canonical-corner gates. `coachable_frontier.py:219/426` re-verifies plant/current track/corridor
evidence and bounds the speed target against driver history; `coaching_runtime.py:813–817` borrows
only minimum speed and preserves human technique. A valid native lap is not automatic eligibility
for any of those consumers. No source fixes, importer, live voice or profile generation were run.

Native trace shape, MOZA-internal practice identity and final preservation/cleanup now have bounded
evidence. Direct cross-system IDs, complete channel semantics/conditions, a supported reuse/export
contract and production consumer gates remain unqualified. Whole Part A and Parts B–D
remain open. #529 and #813 retain their independent dispositions and acceptance.

## Evidence and ownership

Scratch root: `.scratch/moza-qualification/part-a3-live/`. Attempt-one receipts remain under passive/;
attempt-two evidence under attempt2/ includes observer-start-receipt.json, ui-ai-on.json,
delta-boundary1.json and delta-boundary2.json. The independent mapping receipt is under
`.scratch/moza-qualification/part-a3/consumer-audit/controller-presence-20261013T161628Z.json`.
Attribution, continuation ledger and consumer matrix are under backlog-drafts/.
Final receipts include attempt2/native-qualification.json, evaluation-linkage.json,
new-cache-compact.json, observer-exit-failure.json, final-preservation-verification.json,
parent-cleanup-verification.json, final-qualification.json, report.md and final-receipt.json.

Carrier is [#815](https://github.com/agorokh/ac-copilot-trainer/issues/815); SAVE remains
[PR #818](https://github.com/agorokh/ac-copilot-trainer/pull/818). Historical A2 notes and shared
handoffs remain unchanged.
No PR merge or exact-head review-quorum claim is made.
