---
type: handoff
status: active
created: 2026-10-24
updated: 2026-10-24
issue: https://github.com/agorokh/ac-copilot-trainer/issues/529
relates_to:
  - AcCopilotTrainer/03_Investigations/issue-529-g1-mclaren-magione-2026-10-16.md
  - AcCopilotTrainer/03_Investigations/issue-555-cross-worktree-rig-ownership-2026-07-13.md
  - AcCopilotTrainer/03_Investigations/steam-elevation-mismatch-ac-launch-2026-06-16.md
  - AcCopilotTrainer/00_System/invariants/data-immutability.md
---

# Issue #529: retained-state diagnostic, not cold-start acceptance

Operator invoked `/autonomous-deliver 529`. This session uses OpenAI Codex (GPT-6 family),
PowerShell/Python, the normal AC harness, and direct window inspection. The exact model build
is not exposed; the initial issue comment's more specific model label is not established.
Tier-3 MCP was unavailable; the documented prefetch successfully queried `ac_copilot` with
an issue-specific prompt. The returned older cold-start context was reconciled with live
issue comments and the Oct16 archives. Council completed three voices; unsupported proposed
threshold changes and inferred thermal mechanisms were rejected. No implementation helpers spawned.

## Authority and ownership

`gh issue view 529 --repo agorokh/ac-copilot-trainer --json state,labels` returned
`OPEN`, labels `enhancement,epic`. The operator-started run has a creation budget of 2;
none used. Existing owner and decision record:
https://github.com/agorokh/ac-copilot-trainer/issues/529#issuecomment-6387928588.
C1 is closed and is not a live dependency. Prior retained training must not count as an
unseen cold-start run. No acceptance thresholds were changed.

## Retained requirement/output pairs

The current issue body and original gate comment `4952909767` control these clauses.

| Clause / retained requirement | Evidence and status |
|---|---|
| G0: measured sign, steer ratio and shift points in <=2 laps; measured origins | Historical handshake evidence retained; no universal fresh pass inferred. |
| G1: unseen known-archetype combo within 5% of TT top-10 in <=20 autonomous laps at stationary environment | Unmet in Oct16 cold-start; this retained-state diagnostic cannot qualify. P2's three unseen combos remain unverified. |
| G1b: novel archetype <=50 laps, uncertainty-gated exploration and safe-QSS fallback | Historical E30 honesty/fallback evidence retained; no universal fresh acceptance. |
| G2: beat combo/setup-specific 82.7 s Magione floor | Historical repeatable 81.505/81.519 s pair retained; 80.791/95.122 s batch is not repeatable capability proof. |
| G3: envelope/frontier cues and debriefs, human session-over-session delta shrinks | Software delivered historically; human outcome unverified. Operator chose existing sessions; dates/archive IDs, driver identity and assistance details are still required. No AI lap is human evidence. |
| G4: one harness, false-green rate <5%, uncertainty/provenance, falsifications propagate | Batch validity passed, not a fresh global false-green rate. Explicit native-AI attribution rejects plant fitting: policy reconciliation below blocks further training. |

## Runtime evidence (completed diagnostic)

Code and installed Lua provenance: `c5d1948b37ed3ff5060d882c202698168cdfef5c`, match.
Initial OS lock probe: unowned; AC/CM absent. Harness acquired the canonical lock before
launch. Existing Steam/SimHub sessions were inventoried and preserved initially.

Normal command: `python -u -m tools.ac_harness.auto_alien --car ks_mclaren_650_gt3
--track magione --laps 3 --ggv-scale 1.0 --scale-step 0.025 --iterations 2 --max-scale 1.05
--evidence-dir .scratch/harness-evidence/issue529-retained-mclaren-20261024`.
Identification was skipped using the retained Oct16 plant, hash `d88d889cd13b`.
Cached QSS prediction: 91.94 s; all seven L3 corners reverted to safe-QSS.

Steam API initialization initially failed. Both the modal and AC log said so; Steam API
registration read pid/ActiveUser zero. Applied documented graceful `steam.exe -shutdown`,
then relaunched through Explorer; auto-login restored a nonzero registered session. Later
token checks found Steam, CM and AC non-elevated. This establishes recovery, not the exact
original elevation cause. No credentials or settings were changed. The initial cached
window capture showed a menu; reacquiring and activating the current AC window showed the
actual McLaren driving. Shared-memory graphics and physics packets advanced independently.

| Batch | Scale | Out / flying laps, seconds | Verdict |
|---|---|---|---|
| Base | 1.0 | 111.596 / 97.369 / 97.449 | PASS, zero recoveries, no sim death/replacement; three AC-valid archives. |
| Iteration 1 | 1.025 | 109.135 / 95.226 / 95.273 | VALID envelope step, all AC-valid, zero recoveries; base refit was a no-op. |
| Iteration 2 | 1.025 | 109.157 / 95.267 / 95.276 | VALID plant step, zero recoveries; raised one existing lateral bin, fit `f19c614bcd61` retained. Rebuilt QSS remains 91.94 s. |

Evidence root is under this worktree's `.scratch/harness-evidence/`. The saved base
`drive/hud.png` was visually inspected: McLaren cockpit at Magione, displayed best 1:37.369,
matching JSON. No tests/builds ran during timed laps. All nine archives are AC-valid;
no sim death or replacement. Best improved 2.143 s (2.20%) through the scale change;
the refit did not establish an additional pace gain. The 1.05 cap was not reached because
the second iteration was used to validate the plant. Exit 0 means pipeline success, not G1.
The base Layer-0 report flagged nonstationarity: thermal delta 12.036 C, pressure delta
1.926 psi. This includes the out-lap; do not extrapolate that verdict to every flying lap.

Public Track Titan leaderboard was re-read in the browser on Oct24: Assetto Corsa,
Magione, McLaren 650S GT3, All Time, other filters unset. P1 72.035 s, P10 74.784 s
(P10 air/road 26/36 C); 5%-of-P10 threshold 78.5232 s. URL:
https://app.tracktitan.io/leaderboards/assettoCorsa/magione/ks_mclaren_650_gt3.

## BLOCKED: provenance policy and missing human-session selection

`gh issue view 815 --repo agorokh/ac-copilot-trainer --json state,labels,body` returned
OPEN, labels enhancement/python. Its retained Part B says AI/shared/unknown records are
"isolated from human PB/progression and plant fitting", including reliably linked native
copies. `git grep -n 'authority != "human"' c5d1948b37ed3ff5060d882c202698168cdfef5c
-- tools/lap_qualification.py` returned line 577: `if authority != "human" and use != "analysis":`.

Observed production-consumer probe on the unchanged base flying archive, SHA-256
`00b77d984b9975079ca542df54026cacb36d260578b40d061227894b8f4dadfa`:
`qualify_archive(..., use='plant_fit')` allowed `legacy_unknown`; adding an in-memory,
identity/hash-bound AI envelope rejected `control_authority_not_human:ai`, even with all
supported-use flags true. `observe_lap_tyre_state` then returned fit_eligible=false,
reason `archive_qualification:control_authority_not_human:ai`. Source and live policy
were not edited. This is a concrete policy conflict for honestly attributed native
self-play, not evidence that MOZA/imported traces should become eligible.

After fitting/validation ended, canonical `register_attribution` restricted all nine
new archives as AI, bound to their exact stage reports. Readback denied human progression
and plant fitting for all nine; all source bytes retained their hashes. Prior entries
were preserved. Receipt: evidence-root `attribution-receipt.json`; probe:
`provenance-probe.json`. The physically validated derived fit remains preserved as
diagnostic evidence; no further training or production-reference promotion was attempted.

Operator was asked whether to allow only explicitly evidenced native harness plant fits,
keeping human progression/references and MOZA/imports excluded, or retain the blanket
ban. Do not implement that exception without the answer. Separately obtain the selected
G3 session dates/IDs, car/track, user versus son, and control assistance. Preserve both
boundaries while working any independent authorized evidence.

Teardown reacquired the canonical rig lock and pinned AC/CM process creation identities.
Both exited gracefully; Steam exited via its shutdown command; sidecar listener 8765
absent; final lock owner null. Existing SimHub PID 23312 was preserved. Receipt:
`teardown-receipt.json`. `.operational-dod.json` is absent. No product code changed.
Independent finding recorded without filing: fetch updated/read origin/main at the same
SHA but automatic geometric-repack reported missing object 93685d4526aba66c398aa1c32f2faf79b7c2784d;
no repository cleanup or object deletion was attempted. Fan-out: none created.

Verification: `make ci-vault PYTHON=python` passed (117 passed, 3 documented skips).
The initial default branch prefix was rejected by ci_policy; renaming to the permitted
`vault/issue529-retained-diagnostic` fixed it without changing policy. A focused secret
scan of this newly staged node passed. The actual SessionStart handoff consumer selected
and printed this node as newest; `git diff --check` passed. Current owner result:
https://github.com/agorokh/ac-copilot-trainer/issues/529#issuecomment-6388233038.
