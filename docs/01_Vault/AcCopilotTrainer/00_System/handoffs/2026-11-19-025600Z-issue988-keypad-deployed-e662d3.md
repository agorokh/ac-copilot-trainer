---
type: handoff
status: complete
created: 2026-11-19
updated: 2026-11-19
issue: https://github.com/agorokh/ac-copilot-trainer/issues/988
relates_to:
  - AcCopilotTrainer/00_System/handoffs/2026-11-19-000832Z-issue988-existing-keypad-8a14d9.md
  - AcCopilotTrainer/10_Rig/external-racing-controls.md
---

# #988 existing-keypad integration merged and deployed

Software delivery is complete; physical declaration acceptance and the full #988
lap bench remain unverified. Issue #988 stays OPEN. No new usable lap data was
generated for #989 and its Stage 1 remains gated. The operator requested use of
the existing setup, autonomous software work, and physical requests only when
necessary. No firmware flashing or driving took place.

## Delivered behavior

[PR #1014](https://github.com/agorokh/ac-copilot-trainer/pull/1014) merged at
2026-11-19T02:36:31Z as `e662d397e726686d282347c861d4ab5e13b05620`.
Game Point now supports the installed CH552 baseline keyboard firmware through
device-specific, read-only Windows Raw Input. The existing global ownership mutex,
supervisor, profile lifecycle, status and declaration sink are reused. The reader
does not suppress shortcuts, inject keys, write HID output, or claim managed-HID
lease/RGB acknowledgment. Malformed input, stale polling and uncertain device
topology fail closed. Attestation qualification policy and raw lap archives did
not change.

Fresh shortcut readback preserves Ctrl+Alt+A / Content Manager, Ctrl+Alt+M /
Minecraft Launcher and Ctrl+Alt+S / Steam, plus the knob's volume functions.
Minecraft's advertised UWP link has an empty TargetPath normally. Identify a
button by its existing role; outer-button GPIO ordering belongs to the separate
firmware qualification work. Do not repeat the old assignment exercise.

A separate baseline declaration profile is installed under the normal Game Point
settings root. During AC, the existing Content Manager chord declares, the Steam
chord clears, and other attestation bindings do nothing. OS shortcuts continue
to operate. Declare before the scored lap and return to AC before lap start.
Idle bindings do nothing and manual_override is null. Both existing opt-in and
journal settings remain required for recording.

## Review and verification

Final reviewed head: `e0e7fb4de1ed5a6aab55a10c8ce969441f99714c`.
`make ci-fast`: 6,549 passed, 26 skipped, 88.00% coverage; focused combined suites:
178 passed. Required hosted checks were green at that exact head. The final
review round (5968430447) returned zero raw findings from Cursor, Antigravity and
Grok. No Kimi coverage is claimed. Earlier findings were addressed or rejected
with source/native evidence; no unresolved medium-or-higher findings remained.

All four final enforced gates exited zero: reviewer lens, findings, review-round
lease and close intent. Runtime pin:
`77fd08162a73dd6d11af521e8d17792b28095d58`. Head and all paginated review/comment/thread
ledgers were stable across the barrier; merge queue was null. Refs-only #988
intent closed no issue. Incomplete tooling snapshots failed safely earlier and
were replaced with the full pinned runtime outside the public repository; all
gates and CI were rerun without policy skips or weakened enforcement.

Native reader registration and shutdown were observed; INPUTSINK/DEVNOTIFY were
requested without NOLEGACY. A second real controller was refused while the first
remained active. Native process enumeration removed the previous tasklist timeout.
Actual installed frozen-code objects for all six integration modules match the
merged source, and the packaged HID extension is present. Installed self-test
returned HTTP 200 for /tablet/dash and /tablet/voice and stopped its owned sidecar.

The installed normal GUI loaded the normal settings root without a profile env
override, showing active baseline keyboard, existing shortcuts retained,
attestation disabled, prospective human session disabled, sidecar stopped.
No START/Drive action was performed. Process-only SimHub/tablet autostart overrides
were zero during verification; persisted start_simhub remains true and all other
settings except keypad_profiles were preserved.

## Deployment and retained evidence

Canonical checkout `C:\Users\arsen\Projects\ac-copilot-trainer` fast-forwarded
cleanly to the merge under the real RigSessionLock. Installed executable:
`dist\AC-Copilot-Game-Point.exe`, SHA256
`85db8e2df37ebfc818ebdcbacc3b5a77496b6e31461381f1850ccbdd2d212d8d`.
Old executable SHA256:
`bd00db789565bfdf3371a7949a07e8b5d80a847ab044997b1fa3609e1828803a`;
its byte backup is retained.

Profile: `%LOCALAPPDATA%\AC Copilot Trainer\GamePoint\keypad-attestation-baseline.json`,
SHA256 `dc55bb5174a01603762d35dd3f37c8e56c44a07f4797fdf678a35283d4aff238`.
Only settings.keypad_profiles changed, guarded by byte backup and compare-and-swap.
Original curated keypad-profiles.json was not overwritten. Settings SHA256:
before `38bd2180060be06a49782bd440650fd0f7dca32e7e7e28269fb4c39866af3578`,
after `400a6ea78f14fa6a0f073748a3f0a702bafe0194d4494e0c7e5590f091f14541`.

Durable local evidence root:
`C:\Users\arsen\Projects\ac-copilot-trainer\.scratch\issue988-integration-20261118`.
Contains deployment.json, build/sync logs, original byte backups,
installed-frozen-source-proof.json, installed-self-test/result.json,
normal-startup-proof.json and normal-gui.json. Final task receipts are copied into
`receipts-final-e0e-20261119T025600Z` under that root, including CI, review ledgers,
four gate logs/receipt, merge barrier, shortcut readback and rig-final.json.
Earlier receipts remain retained. Runtime archive SHA256:
`01bed6c8de6ea8ec6974a4349c8e1af92864aae54c8daeb5de0a06fdaab50598`.

## Exact remaining physical boundary

The requested one-button physical check received no answer. No declaration
journal exists and no real event is claimed. Temporary capture and both test GUIs
were closed. Attestation, journal and profile override variables are unset in
User/Machine scopes. The normal GUI is closed, port 8765 has no owned listener,
and the rig lock is released. Final rig inventory found no AC or detected driving
harness; two unrelated background Python command lines were unreadable, so this
does not certify exclusive human control. Existing Steam and MOZA Pit House
processes were preserved. No G3 campaign is configured or active.

When the operator is ready, rearm a short disposable-journal test first, then ask
for ONE press and release of the existing Content Manager button. Check exactly
one declaration and preserve its existing shortcut behavior. The collector is
currently CLOSED: a press now will not validate anything. No wheel/pedal or old
keypad reassignment exercise is needed. #988's independent witness/hash/default-off
lap bench remains separate and unrun; do not infer human lap provenance from the
software checks. #989 still needs its qualifying data.

The attached chat worktree is retained intentionally; no removal-capable sync or
stash was used. Shared Current Focus, Next Session and vault indexes are unchanged.
