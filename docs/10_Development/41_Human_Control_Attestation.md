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
| Native game AI | CSP `car.isAIControlled` and `car.isUserControlled` | Counted every frame by the trainer app, stored in the archive as `trace.control_observation` | Complete lap, zero unknown frames, zero AI frames, every frame user-controlled |
| Vendor AI driving | The vendor practice record's `aiIntervened` label | Rolling snapshot file, preserved by the capture monitor | A record read after the lap covers it by session window, matches track and car, matches exactly one lap by duration (1 ms), and labels it not intervened, complete and finalized |
| (operator intent) | Declaration from a rig button via `tools/rig_controls` | Appended to `declarations.jsonl` | Declared before the lap started, at most 20 minutes before it ended, not cleared since. Necessary, never sufficient |

A probe that fails for any reason other than "file not found" is `error`, not `absent`. A torn
journal line, a clock that runs backwards, a duplicate JSON key or an unreadable vendor file all
abstain. A lap that already has a ledger entry or an embedded assessment is never attested.

The decision is `tools.lap_qualification.human_witness_reasons`. The producer and every later
reader call the same function, so a stored verdict is never trusted.

## Policy path

- `register_human_attestation` is the only writer of `authority == "human"`. It needs the opt-in,
  a native archive, a witness that still certifies against the bytes it reads, and no existing
  entry for that lap. `register_attribution` is unchanged and still refuses human authority.
- A certified lap is granted `analysis` and `human_progression` only.
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
python -m tools.human_control_attestation verdict --manifest <manifest.json> --results <results.json>
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
- **Declaration hardware.** The `attest` binding needs the managed keypad firmware, which is not
  flashed (workstation-ops#3863).
- **Other input injectors.** A virtual controller or any path not listed above is not observed.
- **Tamper resistance.** Evidence is structural and hash-bound, not signed. The ledger file is
  the trust anchor.

## Bench session (operator-attended, not yet run)

One rig session, at most 45 minutes, operator present. Do not start it until the three
prerequisites hold.

**Prerequisites**

1. The change is merged and the rig's primary checkout is on it, so new archives carry
   `trace.control_observation`. Check one archive before starting.
2. A working declaration surface (flashed managed keypad with an `attest` binding, or an
   operator decision on another surface).
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

**Arms**

| Order | Arm | Laps | How | Expected |
|---|---|---|---|---|
| 1 | `human` | 6 or more | Out-lap, press the declare button, then drive | Certified (at least 5 of 6) |
| 2 | `vendor_ai_mid_lap` | 2 or more | Declaration left active; switch vendor AI on part-way through one lap and off part-way through another | Abstain |
| 3 | `vendor_ai` | 1 or more | Vendor AI on for the whole lap | Abstain |
| 4 | `vendor_ai_record_missing` | 1 or more | Restart the monitor into `capture-b` without `--vendor-snapshot`, then a full vendor-AI lap | Abstain (`vendor_record_missing`) |
| 5 | `native_ai` (optional) | 2 | AC's own AI on the player car, one switched on mid-lap | Abstain |
| 6 | `project_autonomous` | 4 or more | The existing autonomous harness run, monitor still running | Abstain (`control_map_present`) |

**Labels, then the producer**

Fill the manifest from the paper notes and the archive list **before** running `attest`, and post
its SHA-256 on the issue. Then:

```powershell
python -m tools.human_control_attestation attest --capture-dir "$bench\capture-a" `
  --register --ledger "$bench\bench-ledger.json" --archive <lap1.json> --archive <lap2.json> ... > "$bench\results.json"
python -m tools.human_control_attestation verdict --manifest "$bench\manifest.json" --results "$bench\results.json"
```

Use `capture-b` for the laps captured in the second monitor run. The bench ledger is a scratch
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
