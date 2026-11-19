---
type: handoff
status: draft
created: 2026-11-18
updated: 2026-11-18
issue: https://github.com/agorokh/ac-copilot-trainer/issues/988
relates_to:
  - AcCopilotTrainer/00_System/handoffs/2026-11-16-112629Z-issue988-software-prep-4b6c92.md
  - AcCopilotTrainer/10_Rig/external-racing-controls.md
---

# #988: existing-keypad software compatibility in progress

Current operator instruction: fix the integration using the existing setup; own
software work and ask only for necessary physical actions. Earlier launcher-button
assignments remain established. No firmware change or general reassignment test.
Decision record: issue comment 6995280232. #988 retains the bench and independent
witness/hash/default-off predicates. #1006 car/shaker actions and #3863 firmware
qualification are not assigned here.

## Implementation and observed checks

An explicit baseline keyboard backend shares Game Point's existing rig_controls
worker, ownership, profile reload and status. Raw Input identifies one CH552 keyboard;
only its known Ctrl+Alt+A/M/S button events feed the existing attest action. It
does not suppress existing shortcuts or inject input. It reports no managed-HID
lease or RGB acknowledgment. A separate example profile declares on A and clears
on S while AC runs; all remaining attestation bindings are no-ops. Attestation
still requires both existing process-scoped opt-in variables.

Initial focused tests passed (77); first native reader probe exposed Windows'
initial device-arrival announcements invalidating the source. Corrected to reject
the selected device's removal/replacement/ambiguity, while accepting unchanged
initial topology. Regression tests added: 79 focused tests pass. Native reader
registered, pumped and closed cleanly on the rig without output reports or a
declaration. Initial format/lint errors corrected. No real lap evidence generated.

The production Game Point supervisor probe exposed the old tasklist subprocess's
400 ms timeout. Replaced it with a native Toolhelp executable-name snapshot,
failing closed on incomplete enumeration. The same real probe now reports active,
idle baseline keyboard, attestation disabled; twenty process-context reads took
0.2161 seconds total. Windows returned INPUTSINK (256) and no NOLEGACY flags;
registration was empty before and after supervisor shutdown. Requested registration
also enables DEVNOTIFY. Receipt: `.scratch/issue988-integration/native-launcher-proof.json`.
Unknown keys reset partial chords; callback exceptions remain visible even with
empty messages. Combined focused suites now pass 171 tests. Draft implementation
carrier: https://github.com/agorokh/ac-copilot-trainer/pull/1014.

Final first-head ci-fast passed 6542 tests, 26 skips, 88.00% coverage, all checks.
The actual packaged UI reported active baseline input with attestation disabled;
owned endpoint self-test passed and shutdown released the listener. Native second-
instance proof refused another controller while the original reader remained
active. Receipt: `.scratch/issue988-integration/native-ownership-proof.json`.

Round 1 reviewed df36d168: Cursor's Toolhelp completion concern is addressed by
clearing last-error before each read and matching the existing entry_launcher
Next-call compatibility convention (0 or 18). First-call failure always abstains,
and explicit Next errors discard partial results. Antigravity's runtime dependency
concern is addressed by exposing availability through the existing Actions
integration boundary. Grok's suggestion to use SimulatedOwnership for real
baseline hardware is rejected: Ownership is solely a machine-wide mutex, with no
HID open, lease or output. Removing it permits duplicate declaration dispatchers.
The real two-instance proof above exercises this exact distinction. Focused
regressions now pass 175 tests. No attestation qualification policy changed.

One isolated physical declaration check is awaiting the operator's response.
Candidate Game Point is scoped to a disposable validation-only journal, with no
AC session or capture monitor started; normal user/machine opt-in remains unset.

Round 2 on 865af62 passed the independence floor: Antigravity and Grok returned
zero findings (review 5968017293); Cursor did not run because of a non-quota
error. Exact-head full ci-fast passed 6546 tests, 26 skips, 88% coverage, with
required hosted checks green. One intervening local policy run caught the private
gate-runtime extraction under scratch. Moved that input outside the public tree
to the product DeveloperTools directory and reran the complete check successfully;
no policy/test skip was added.

Own pre-merge audit then reproduced two decoder failures in regression tests:
valid RAWINPUT union padding was rejected, and KEYBOARD_OVERRUN_MAKE_CODE with
an otherwise recognized VKey was accepted. The decoder now requires a complete
keyboard member while permitting trailing union storage, and rejects both the
overrun scan and invalid VKey range. Microsoft RAWINPUT/RAWKEYBOARD definitions
ground these cases. Both tests failed before the change; 177 focused tests now
pass. Fresh native supervisor registration/read/default-off/shutdown proof passes
(20 context reads in 0.1899 s). The old validation GUI was closed before updating
the candidate; no physical declaration has been recorded. The existing one-button
prompt is paused until the updated package is ready. No new assignment exercise.

Tier-3 task-specific canonical prefetch succeeded for ac_copilot, retaining its
endpoint-drift warning. Council attempt 454c7b816d3c4973af305af598ed144e had 1/6
answers and no quorum; five seats failed. Its answer discussed macOS despite this
Windows brief, so its platform recommendation was rejected. Windows APIs grounded
in Microsoft Raw Input/RegisterRawInputDevices documentation. Self-hosted PR review
is still required; the incomplete council is not merge admission.

## Remaining work

Full CI, independent exact-head review, merge, canonical Game Point rebuild and
installed profile/status verification. Then one physical end-to-end declaration
check, if needed; no old launcher assignment exercise. #988 bench verdict remains
open and #989 stage 1 remains gated. No new issue or spawned agent created.
