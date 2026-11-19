# Capture-time human-control attestation

Issue [#988](https://github.com/agorokh/ac-copilot-trainer/issues/988) (card `REX-20261114-01`).
**Status: experimental and default off.** The offline rule is implemented and tested. The
acceptance verdict is open until the operator-attended bench session below has run; until then
no real lap is certified and the producer must stay disabled.

## Contract

A native lap leaves capture either with `verified_human_control` evidence bound to its payload
hash, or as `unverified` with every specific reason. The producer uses process-level signals, not
input statistics, and never infers a human from a missing signal.

| Non-human path | Signal | Where it is read | Certifies only when |
|---|---|---|---|
| Project autonomous driver | CSP Custom-AI sections `Car0` / `CarControls0` (bare and `Local\`) | Read-only `OpenFileMapping` probe every 100 ms by the capture monitor | Every sample from the declaration to the lap end reads *absent*, no gap over 500 ms, and AC's own `acpmf_physics` opens through the same opener (positive control) |
| Native game AI, pause, replay | CSP `car.isAIControlled`, `car.isUserControlled`, `sim.isLive`, plus wall-clock elapsed time | Counted on every frame of an open lap by the trainer app, stored in the archive as `trace.control_observation` | Complete lap, zero unknown frames, zero AI frames, every frame user-controlled and live, at least 10 frames per second, and wall-clock elapsed within 2.5 s of the lap time |
| Vendor AI driving | The vendor practice record's `aiIntervened` label | Rolling snapshot file, preserved by the capture monitor | The latest read of a record saved after the finish covers the lap by session window, matches track and car, matches exactly one lap by duration (1 ms) with the same lap number, and labels it not intervened, `eligible`, complete and finalized. No read of that vendor session disagrees or marks the lap number as AI, and the last look at the file succeeded |
| (operator intent) | Declaration from a rig button via `tools/rig_controls` | Appended to `declarations.jsonl` | Declared before the lap started, at most 20 minutes before it ended, not cleared since. Necessary, never sufficient |

A probe that fails for any reason other than "file not found" is `error`, not `absent`. A torn
journal line, a clock that runs backwards, a duplicate JSON key in a journal, vendor file or
archive, or an unreadable vendor file all abstain. A vendor record saved before the latest
possible finish is never a candidate, and a failed or malformed later read is never skipped in
favour of an earlier clean one. A lap that already has a ledger entry or a `qualification` key of
any value is never attested.

AC lap time excludes paused time, and the capture window is derived from it. A paused lap would
start before the probed window, so a lap whose wall-clock elapsed time disagrees with its lap
time abstains (`native_lap_wall_clock_mismatch`), as does one with a paused or replay frame
(`native_lap_not_live`).

Run `attest` after the session has ended, so the latest vendor read is the final one.

The decision is `tools.lap_qualification.human_witness_reasons`. The producer and every later
reader call the same function, so a stored verdict is never trusted.

## Policy path

- `register_human_attestation` is the only writer of `authority == "human"`. It needs the opt-in,
  a native archive, a witness that still certifies against the bytes it reads, and no existing
  entry for that lap. `register_attribution` is unchanged and still refuses human authority.
- A certified lap is granted `analysis` and `human_progression` only.
- **Revoking one lap.** Registering a restrictive fact (`ai`, `shared` or `unknown`) for the exact
  same lap with `register_attribution` replaces its human attestation. It is the only
  replacement the ledger allows, it is final, and nothing can replace a restrictive fact.
- `qualify_archive` rechecks the witness, the payload hash and the in-archive control counts on
  every call. With the opt-in unset, an attested lap is denied every use except `analysis`
  (`human_control_attestation_disabled`): unsetting the variable is the revocation switch.
- Embedded assessments from other origins behave exactly as before.

## Configuration

| Variable | Meaning |
|---|---|
| `AC_COPILOT_HUMAN_CONTROL_ATTESTATION` | Only the value `1` enables the producer, registration and the human-only uses of attested laps. Unset by default. |
| `AC_COPILOT_HUMAN_DECLARATION_JOURNAL` | File the rig-button `attest` binding appends to. Unset means the button reports "attestation not enabled". |

Rig-button binding (buttons only, never a knob detent):

```json
{"action": "attest", "name": "human_control.declare"}
```

`human_control.clear` withdraws the declaration.

## Commands

```powershell
python -m tools.human_control_attestation monitor --capture-dir <dir> --vendor-snapshot <file>
python -m tools.human_control_attestation attest --archive <lap.json> --capture-dir <dir>
python -m tools.human_control_attestation scorecard --ledger <lap-attributions.json> --laps <dir>
python -m tools.human_control_attestation verdict --manifest <manifest.json> --results <a.json> --results <b.json>
```

`attest` writes nothing unless `--register` is given. `scorecard` is read-only and exits non-zero
if any already-attributed lap would be certified.

## What is not established

- **Live behaviour of every signal.** The CSP field exists in the definitions shipped with the rig
  install (`extension/internal/lua-sdk/ac_apps/lib.lua`), but whether it reads true for AC's own
  AI on the player car, and what it reads under the Custom-AI hijack, has not been observed.
- **Vendor record coverage.** On the rig the record is one rolling file
  (`training-evaluation-snapshot-v1.json`). On 2026-11-14 it was last written 2026-10-15 while
  59 native laps in 27 sessions were captured after it, so it is not written for every session.
  A lap without a covering record always abstains.
- **Declaration hardware.** Game Point supports the existing baseline keypad through the
  explicit `baseline_keyboard` profile backend, as well as the managed HID backend.
  The baseline path preserves Ctrl+Alt+A/M/S and their application actions; it does not
  require reflashing or repeating the old button-assignment exercise. One real declaration
  through the new software path still needs an operator-attended check.
- **Other input injectors.** A virtual controller or any path not listed above is not observed.
- **Track layout in the vendor join.** The vendor key's layout field is not understood, so only
  track and car are compared.
- **Vendor lap numbering.** The join assumes the vendor's lap number equals the archive's, as in
  the one observed session and as `tools/moza_ingest` already requires. If they differ on the
  rig, every lap abstains.
- **Vendor save timing.** A record counts only if it was saved at least a full second after the
  archive's (second-resolution) finish time. If the vendor saves once at each lap completion, a
  lap becomes certifiable only after the next save, so the last lap of a stint never certifies.
  The verdict also depends on the capture as recorded: a failed look at the vendor file after
  the deciding read, or a later read that no longer lists the lap, abstains.
- **Frames the app never sees.** Frames where the app returns before sampling (no car, main
  menu) are not counted; only the frame-rate floor and the wall-clock rule bound them.
- **Tamper resistance.** Evidence is structural and hash-bound, not signed. The ledger file is
  the trust anchor.

## Bench session (operator-attended, not yet run)

One rig session, at most 45 minutes, operator present. Do not start it until the three
prerequisites hold.

**Prerequisites**

1. The change is merged and the rig's primary checkout is on it, so new archives carry
   `trace.control_observation`. Check one archive before starting.
2. A working declaration surface: the existing baseline keypad with Game Point's
   `profiles.attestation-baseline.json`, or a managed keypad with an `attest` binding.
   Stage a separate profile; preserve the user's ordinary mappings.
3. Racing Lab observes the session (launch from it) so the vendor record is written.

**Setup** (one PowerShell window in the interactive desktop session, never over SSH)

```powershell
$bench = "$env:USERPROFILE\Projects\ac-copilot-trainer\.scratch\issue988-bench"
$env:AC_COPILOT_HUMAN_CONTROL_ATTESTATION = "1"
$env:AC_COPILOT_HUMAN_DECLARATION_JOURNAL = "$bench\capture-a\declarations.jsonl"
'{"schema_version": 1, "entries": []}' | Set-Content -Encoding ascii "$bench\bench-ledger.json"
python -m tools.human_control_attestation monitor --capture-dir "$bench\capture-a" `
  --vendor-snapshot "$env:LOCALAPPDATA\MOZA Racing Lab\training-evaluation\training-evaluation-snapshot-v1.json"
```

Start the keypad worker from a shell with the same two variables. Set them for the bench shells
only, never machine-wide. Note the wall-clock time of every arm change on paper.

Game Point normally owns the worker. In the bench shell, point
`AC_COPILOT_KEYPAD_PROFILES` at `tools/rig_controls/profiles.attestation-baseline.json`
(or a validated, separate installed copy), then launch Game Point normally. The example
uses the already-established Content Manager button to declare and Steam button to clear.
Their normal application shortcuts remain active, so return to AC **before** the scored
lap starts; do not declare by switching windows in the middle of a scored lap. The
Keypad row distinguishes the read-only baseline backend, disabled attestation and the
last recorded declaration. A declaration alone never grants human authority.

**Arms**

| Order | Arm | Laps | How | Expected |
|---|---|---|---|---|
| 1 | `human` | 6 or more, plus one extra | Out-lap, press the declare button, then drive. The extra lap lets the vendor save again after the sixth | Certified (at least 5 of 6) |
| 2 | `vendor_ai_mid_lap` | 2 or more | Declaration left active; switch vendor AI on part-way through one lap and off part-way through another | Abstain |
| 3 | `vendor_ai` | 1 or more | Vendor AI on for the whole lap | Abstain |
| 4 | `vendor_ai_record_missing` | 1 or more | Restart the monitor into `capture-b` without `--vendor-snapshot`, press declare again, then a full vendor-AI lap. Before attesting, copy `capture-a\declarations.jsonl` into `capture-b` so the vendor record is the only missing signal | Abstain (`vendor_record_missing`) |
| 5 | `native_ai` (optional) | 2 | AC's own AI on the player car, one switched on mid-lap | Abstain |
| 6 | `project_autonomous` | 4 or more | The existing autonomous harness run, monitor still running | Abstain (`control_map_present`) |

**Labels, then the producer**

Fill the manifest from the paper notes and the archive list **before** running `attest`, and post
its SHA-256 on the issue. Then:

```powershell
python -m tools.human_control_attestation attest --capture-dir "$bench\capture-a" `
  --register --ledger "$bench\bench-ledger.json" --archive <lap1.json> --archive <lap2.json> ... > "$bench\results-a.json"
python -m tools.human_control_attestation attest --capture-dir "$bench\capture-b" `
  --register --ledger "$bench\bench-ledger.json" --archive <lapN.json> ... > "$bench\results-b.json"
python -m tools.human_control_attestation verdict --manifest "$bench\manifest.json" `
  --results "$bench\results-a.json" --results "$bench\results-b.json"
```

Each archive goes to the `attest` call for the capture directory it was recorded under, and
`verdict` takes one `--results` per call. The bench ledger is a scratch
file: the production ledger is not written, so the signals are tested rather than the
"already attributed" guard.

**Manifest template**

```json
{
  "schema_version": 1,
  "issue": 988,
  "session_date_utc": "YYYY-MM-DD",
  "car_id": "",
  "track_id": "",
  "vendor_record_available": false,
  "laps": [
    {"session_uuid": "", "lap_n": 0, "arm": "human", "note": ""},
    {"session_uuid": "", "lap_n": 0, "arm": "vendor_ai_mid_lap", "note": "AI on at about ...s"},
    {"session_uuid": "", "lap_n": 0, "arm": "vendor_ai", "note": ""},
    {"session_uuid": "", "lap_n": 0, "arm": "vendor_ai_record_missing", "note": "capture-b"},
    {"session_uuid": "", "lap_n": 0, "arm": "native_ai", "note": "optional arm"},
    {"session_uuid": "", "lap_n": 0, "arm": "project_autonomous", "note": ""}
  ]
}
```

Set `vendor_record_available` to `true` only if `capture-a\vendor\` holds a record whose session
window covers the Racing Lab stint.

**Verdict** (fixed by the issue, applied by `verdict`)

- **PASS**: no non-human or mixed lap certified, and at least 5 of 6 human laps certified.
- **FAIL**: any non-human or mixed lap certified, or a certification without hash binding.
- **INCONCLUSIVE**: fewer than 6 human laps, fewer than 4 laps in a non-human arm, or the vendor
  record unavailable for the session.

**Stop rule.** The first false certification ends the test. Leave the variable unset; the
producer stays disabled.
