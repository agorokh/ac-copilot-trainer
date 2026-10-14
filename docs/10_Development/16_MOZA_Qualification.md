# MOZA data qualification

Issue [#815](https://github.com/agorokh/ac-copilot-trainer/issues/815) separates
research, normalization, reporting and live activation. Part A is complete.
Part B implements native control provenance first, then the local cache reader.
This document records the implementation contract. Validation status is retained
on the Part B pull request.

## Native recordings and control authority

The trainer can record a MOZA-assisted lap as `source=in_game`, including a PB
flag. Those fields describe collection and timing, not who controlled the car.
The raw archive remains immutable. An explicit attribution record binds control
evidence to its original byte hash, canonical payload hash and session/lap
identity. It must also apply when a consumer receives the parsed dictionary or
a copy of the same archive.

One attribution ledger is selected through `AC_COPILOT_LAP_ATTRIBUTIONS`, with
the canonical AC Documents app journal as the default. Consumer checks resolve
that ledger at archive boundaries. Invalid, duplicate or mismatched attribution
cannot fall back to an unattributed lap or be overridden by permissive embedded
metadata. Tests and offline qualification use an isolated ledger.

The default is `cfg/extension/state/lua/app/AC_Copilot_Trainer/ac_copilot_trainer/journal/lap-attributions.json`
under AC Documents. `AC_COPILOT_LAP_ARCHIVE_DIR`, `AC_COPILOT_CSP_STATE_DIR`
and `AC_COPILOT_AC_USER_DIR` follow existing journal-location overrides. Set
`AC_COPILOT_LAP_ATTRIBUTIONS` explicitly when working with an isolated corpus.

The registration entrypoint accepts a previously prepared evidence envelope:

```powershell
$env:AC_COPILOT_LAP_ATTRIBUTIONS = "C:\selected\journal\lap-attributions.json"
python -m tools.lap_qualification register --archive "C:\selected\lap.json" --qualification "C:\selected\qualification.json" --ledger $env:AC_COPILOT_LAP_ATTRIBUTIONS
```

The evidence envelope is produced with `build_qualification` from the exact
archive and observed evidence. Registration binds and appends the restriction;
it does not infer control from a filename, lap time or PB flag. The registration
path accepts AI/shared/unknown attribution and cannot grant human or live-reference
eligibility. Conflicting identity is an error; an identical repeat is idempotent.
The ledger option selects the registration destination, while the environment
setting selects the same authority for subsequent direct-dictionary consumers.
An explicitly configured missing or unreadable ledger fails closed.

AI, shared and unknown control are distinct from human control. Managed records
with those authorities cannot count toward human PB/progression or plant fitting.
Unrelated historical archives retain their existing behavior and are explicitly
unattributed; this change does not certify them as human or rewrite their bytes.

An existing driver profile whose retained lap/session identities overlap a new
restriction requires a deliberate rebuild. Strict loading or merging refuses it;
ordinary loading parks its derived history while retaining preferences and focus
corners. The saved profile is not edited, and missing historical identities cannot
be used to certify old aggregates. Duplicate managed identities exclude every
conflicting copy before corpus selection.

## Shared consumer checks

One shared policy evaluates the intended use, identity, channel semantics,
validity and coverage. Archive-facing reference, Coach/observer, MAP, report,
profile and plant boundaries retain their stricter existing checks. A requested
use is not permission to bypass missing evidence. Track Titan behavior and the
existing advisory/voice pipeline remain in place.

Programmatic callers use `qualify_archive(record, use=..., expected_combo=...)`.
Its result contains `allowed`, `reason`, `reasons`, `managed` and `authority`.
Uses are `analysis`, `map`, `reference_comparison`, `live_reference`,
`human_progression` and `plant_fit`. The shared policy resolves provenance even
for direct parsed inputs; a loader-only guard is insufficient. The expected
combo, where required, comes from the consuming session or comparison subject,
not from the proposed reference certifying itself.

An explicitly selected `archivePath` is authoritative over an inline trace. A
missing or invalid selected file does not fall back to unattributed telemetry for
advice or rolling-best updates. Directly supplied profile mappings receive the
same contamination check as profile files. Legacy reference matching retains its
historical combo fallback, while managed qualification still requires independent
car/track/layout evidence.

## MOZA caches

Only explicitly selected local files are read. The reader checks stable bytes
and records hashes and source versions. Processed/chart data stays distinguishable
from measured native telemetry. Unsupported steering conversion, elapsed origin
or coordinates stay unavailable. The importer does not fabricate missing channels,
inherit the reference builder's default valid/PB flags, or label MOZA as MoTeC.

Parsing an inspection artifact is separate from qualifying it as a reference.
Zero eligible evaluated laps cannot supply coaching advice even when scores exist.
No live reference, voice activation, rig launch or controller action follows from
Part B. Those decisions remain in later Parts of #815.

```powershell
python -m tools.moza_ingest --cache "C:\selected\view.json" --output "C:\selected\inspection.json"
python -m tools.moza_ingest --cache "C:\selected\view.json" --evaluation "C:\selected\evaluation.json" --output "C:\selected\inspection-with-evidence.json"
```

Each output must be a new file in an existing directory. The CLI rejects input
aliases and existing output paths, reads bounded files twice, and publishes the
complete output atomically. `accepted_for_inspection` means the known
`tracecore.view.v1` representation was parsed; all six production-use flags remain
false. Rejected schema, identity, numeric or file-stability checks return a reason
and nonzero exit status. Reads of multiple files are not an atomic app snapshot.

The optional evaluation must join exact producer lap IDs and agree on duration,
lap number and known completion/validity. `aiIntervened=true` records shared/assisted
control; false or absent does not establish a human lap. Zero evaluated laps
produce unavailable advice even when score fields exist. Producer events remain
unqualified annotations. App/resource versions absent from the selected view stay
unknown; the importer never searches neighboring application stores.

This is a Python sidecar/offline boundary. It does not alter the Lua recorder's
raw PB labels or its current-session state. MOZA inspection artifacts are not
MoTeC references, and the existing Lua importer requires `motec_csv`. Any later
live integration must explicitly address activation and control ownership under
Part D; installing this code alone does not retroactively change the running rig.

## Part C: offline report boundary

The offline integration uses the existing session-review report and Game Point
entrypoint. Its file selection is separate from the live reference and voice
settings. Generating or opening a report must not start AC, the sidecar, a
controller or playback, or update the attribution ledger or driver profile.

Native telemetry is analyzed only when the shared policy permits analysis.
Matched native comparisons retain their independent combo and qualification
checks. A cache inspection report explains available processed channels and
rejection reasons; it cannot invent missing measured channels or corner results.

Optional MOZA producer advice uses the existing `CoachingOracle` and
`CoachingSnapshot` interface. Numeric traces, scores and event annotations are
separate from actual supported advice. Empty or zero-eligible evaluations remain
unavailable. Unknown producer advice schemas must remain unavailable rather than
be interpreted as expert coaching. Track Titan and the current voice pipeline
retain their existing behavior. Shadow replay and activation remain Part D.

Game Point's **OFFLINE REPORT** action selects a native archive or MOZA view,
with optional matched native and evaluation files. Its remembered selections
use `moza_offline_file`, `moza_offline_native_file`,
`moza_offline_evaluation_file` and `moza_offline_oracle` in the existing Game Point
settings file. Oracle inspection defaults off. These settings do not select a
live reference. Derived HTML, Markdown and JSON use the existing report writer
under Game Point's `journal/reports`; source files remain read-only.

Selecting the MOZA workflow does not itself attribute a native lap to MOZA or
certify human control. The report shows the archive's source and resolved
authority. It reports an observed lap time separately from human achievements,
and gives explicit reasons when numeric analysis or a native comparison cannot
be produced. Selecting a matched file is not proof of shared recording identity.

The currently observed producer schema has no validated expert-advice contract.
`MozaOfflineOracle` implements the existing interface but returns no
`CoachingSnapshot` for these inputs. Its inspection result preserves source
hashes, exact producer linkage where available, evaluation eligibility and
unqualified event metadata. A score, event label or unknown eligibility string
cannot create a coaching message or confidence value. Supporting a future
producer advice schema requires separate evidence and tests.

## Part D: silent voice validation

Game Point's offline report can opt into silent voice validation with an
explicitly selected reference archive. The driving recording and reference have
different roles: AI/shared driving samples may exercise the observer and Coach v2,
but cannot become a human technique reference through replay. Both inputs retain
their original bytes and control attribution. The reference must pass the existing
independent combo and reference checks; selecting it is not an eligibility grant.

Replay uses the existing observer, Coach v2, phrase resolver and scheduler with
recorded elapsed time, an injected clock and recording-only playback. Observer and
Coach v2 are separate replay modes, not duplicate producers in one voice stream.
No audio device, sidecar, simulator or controller is started. No live reference,
voice setting, attribution ledger or driver profile is changed. Ambient alien-line
or driver-profile configuration must not silently affect the selected-file test.

Evidence distinguishes measured brake onsets from reference marks, emitted
advisories from dispatched phrases, and suppression from missing evidence. Retain
corner identity, expected and actual event times, lead time, staleness, deduplication
and phrase choices. A modeled clip duration is not measured audible latency. A
cue-free run cannot count as successful timing coverage. Synthetic contract tests
remain labeled separately from replay of a retained recording.

The report records separate engineering-validation and human-evaluation decisions.
Legacy references permitted by the existing policy retain `legacy_unknown`
authority; replay does not certify them human. Unknown control, unmatched conditions
or unvalidated technique keep human evaluation unavailable even when the software
replay succeeds. Known AI/shared references retain their existing rejection. The
live-activation decision remains explicit and does not execute an activation.

In **OFFLINE REPORT**, select the native driving recording, check **Silent voice
validation**, and select the separate technique reference. **SAVE SELECTIONS &
GENERATE** writes the usual HTML, Markdown and JSON reports. The optional settings
are `moza_offline_shadow` (default false) and `moza_offline_reference_file`;
neither changes the live `reference_archive` or voice settings. Missing or rejected
references leave numeric inspection available and give a specific replay reason.
MOZA processed caches remain inspection-only.

The `moza_shadow` result retains input hashes, attribution, condition comparisons,
measured brake events and a cue-by-cue scheduler decision log for each producer.
Lead to recorded brake onset, the producer's requested lead budget and modeled
clip finish are separate checks. Missing dispatch or an unmatched event stays
unavailable, never zero. Corner indices identify the reference's segmented windows;
they are not certified track corner names. Both producers start with fresh memory
and replay one recording once. Coach v2's assessment phase may therefore produce
no cues; that does not prove timing coverage. No driver history is read or invented.
