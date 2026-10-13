---
type: handoff
status: active
memory_tier: canonical
created: 2026-10-13
updated: 2026-10-13
issue: https://github.com/Atelier-AppliedAI/workstation-ops/issues/3863
relates_to:
  - AcCopilotTrainer/00_System/Current Focus.md
  - AcCopilotTrainer/10_Rig/external-racing-controls.md
  - AcCopilotTrainer/00_System/handoffs/2026-10-13-154636Z-keypad-adapter-guide-codex.md
---

# Adapter wiring and test profiles saved on main; hardware remains deferred

[PR #829](https://github.com/agorokh/ac-copilot-trainer/pull/829) MERGED
`c53b187605276322ed80fb3f50d9ddd34dc60992` at 2026-10-13T16:08:55Z, from exact reviewed head
`cf3732dbff517732aa9f71c0bb04a2eb2d1edea9`. Author vendor OpenAI/Codex; independent Antigravity and
Grok reviewed the exact head with zero raw findings. Quorum floor 1 was satisfied
by both eligible seats. Complete paginated comments, reviews, inline comments and
threads were audited; no unresolved threads. CI/policy/conformance passed.
The final policy read found no merge queue or enforced findings workflow declared
by this public spoke; its existing policy was preserved, with executed exact-head
quorum and complete feedback/CI preflight. Post-merge classification reported no
flags. Primary main is synced and the owned feature worktree/branch were removed.

Canonical [arrival guide](../../../../../firmware/keypad/qualification/README.md)
and adjacent test-red/test-green/test-auto JSON are linked from firmware/controller
READMEs, the rig plan and the earlier arrival SAVE. Manual profiles exercise all six
A-F inputs; automatic colour testing uses no-ops in every profile. Production
parser/controller simulation passed both manual profiles and seven automatic cases;
19 local links resolve. GitHub Ubuntu/Python 3.11 full ci-fast passed 4,319 tests,
78 skips. Local formatting/lint/policy/security checks passed; 27 local full-suite
fixture imports were limited by upstream Lupa 2.8 deliberately excluding luajit21
on macOS. No dependency or production code was changed to bypass that limitation.

The four PC staging files match the canonical source hashes; all three profiles
validate on Windows with zero HID output. Fresh PC read found keypad_profiles and
user/machine override unset, zero prepared-EXE/standalone-controller processes, and
unchanged recovery ZIP, EXE, managed HEX and baseline HEX hashes. Both images remain
inside DO-NOT-FLASH/. Working racing JSON and installed launcher settings were not
changed. No firmware upload, erase, driver installation, controller activation,
shaker/audio action or AC launch occurred.

Resume under OPEN workstation-ops #3863 when the adapter arrives: inspect labels,
assemble unpowered with Uno disconnected, read ROM identity only, return to all six
stock controls twice, and reconcile GPIO before selecting any image. Then qualify
both variants, six controls, red/green focus, lease loss, power/sleep/reconnect and
repeatable recovery. The baseline is not a factory backup. Shaker targets remain
unavailable. Evidence: M5 `.codex/artifacts/keypad-profiles-20261013/adapter-save/`;
PC `WorkstationOps/Recovery/keypad-profiles-prepared-20261012/adapter-guide/`.
