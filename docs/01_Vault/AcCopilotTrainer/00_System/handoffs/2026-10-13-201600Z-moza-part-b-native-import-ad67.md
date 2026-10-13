---
type: handoff
status: active
memory_tier: canonical
created: 2026-10-13
updated: 2026-10-13
issue: https://github.com/agorokh/ac-copilot-trainer/issues/815
relates_to:
  - AcCopilotTrainer/00_System/Current Focus.md
  - AcCopilotTrainer/00_System/invariants/data-immutability.md
---

# Part B: native control provenance before MOZA cache import

Implementation: [PR #834](https://github.com/agorokh/ac-copilot-trainer/pull/834),
branch `feat/issue-815-moza-qualification-import`. Part A research
remains in separate PR #818. Three implementation agents used GPT-6 Astra with
Extra High effort as requested. Initial draft #833 used a branch prefix rejected
by repository CI; the replacement carrier uses the existing accepted prefix.
The naming policy is unchanged.

The Python archive boundary now resolves one append-only attribution ledger by
original bytes, canonical payload and full session/lap identity. Known assisted
native `in_game` records retain raw PB labels but cannot supply human progression,
technique references or plant fitting. Direct dictionaries use the same gate as
path loaders; a failed original-byte check stays denied on subsequent checks.
Malformed or unavailable configured evidence cannot fall back to legacy behavior.
Unselected historical laps remain explicitly unattributed, not certified human.

Shared checks cover Coach/observer, MAP/reference comparison, debrief/report,
profile, rolling-best/brake calibration and plant/self-play corpus boundaries.
Duplicate managed identities exclude every participant. Existing profile history
with attributed lap/session overlap requires rebuilding; on-disk profiles and
manual preferences are preserved. Identity-free historical aggregates cannot be
retroactively certified or repaired. Track Titan's existing paths and stricter
reference guards remain; no new voice engine is introduced.

The versioned explicit-file importer preserves sparse processed channels and
producer metadata without inventing native steering, elapsed origin, world
coordinates or valid/PB defaults. Inspection acceptance grants none of the six
production uses. Exact optional evaluation joins preserve AI intervention, while
zero evaluated laps remain unavailable advice. Inputs are bounded and checked
for stable bytes; output is an exclusive atomic publication. No source files are
rewritten or credential/profile stores discovered.

Protected-copy checks exercised the actual 137.983-second native archive through
the production loader, direct-dictionary policy, profile eligibility and live
reference factories. Original bytes stayed unchanged, human/reference/plant uses
were denied, and changed bytes or stale identity stayed denied. Both A3 MOZA
cache copies parsed as inspection artifacts with every production use rejected.
The original post-lap evaluation JSON was not retained in the selected evidence;
its exact optional join is tested synthetically, not claimed as real-file proof.
Raw/personal traces and proof outputs remain gitignored under `.scratch/`.

The 183 new synthetic cases pass. GitHub full `make ci-fast` on implementation
commit `7ab8e4c` passed 4,513 tests with 15 skips and 87.07% coverage. The Windows
run initially exposed incompatible global MCP and a missing C compiler; validation
uses the existing MCP-v2 project venv plus an isolated Zig/Clang compiler bridge.
All ten firmware harness tests then passed without source changes. External
exact-head review and the final Windows result remain recorded on the PR.

Subsequent integration review found and corrected direct-profile and
inline-trace/selected-path routes that could bypass attribution. Selected-file
failure now parks live advice/rolling-best, and managed AI subjects remain
available for qualified offline analysis without supplying live socket advice.
Antigravity also identified a legacy reference-selection regression: matching now
uses its historical fallback separately from independent qualification context.
Regression tests cover these triggers; final review/CI evidence belongs to the
corrected head on the PR, not the earlier implementation-head receipts.
See [qualification/import contract](../../../../10_Development/16_MOZA_Qualification.md)
for entrypoints and limitations.

No live attribution ledger, driver profile, rig settings or running process was
changed. This is the Python sidecar/offline integration boundary; Lua recorder
PB flags and current-session state are not migrated. Part C reporting features,
Part D activation/ownership/silent-replay and audible physical acceptance remain
unassigned and open under #815. No reference or voice activation follows from
this implementation.
