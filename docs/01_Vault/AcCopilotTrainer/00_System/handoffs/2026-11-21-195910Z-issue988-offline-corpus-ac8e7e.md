---
type: handoff
status: active
created: 2026-11-21
updated: 2026-11-21
issue: https://github.com/agorokh/ac-copilot-trainer/issues/988
relates_to:
  - AcCopilotTrainer/00_System/handoffs/2026-11-19-025600Z-issue988-keypad-deployed-e662d3.md
  - AcCopilotTrainer/00_System/handoffs/2026-11-14-210226Z-post-merge-pr997-988-attestation.md
---

# #988 offline criterion passes on all 174 original archives

The offline criterion passed. Live acceptance is **BLOCKED pending operator availability** for
the keypad retest and the previously approved, operator-attended bench. #988 remains open.

## Evidence and remaining acceptance

| Retained requirement | Result |
|---|---|
| Zero certifications among the original 174 AI or assisted laps | **Pass.** 174 evaluated, 0 missing, 0 unreadable, 0 certified. All 174 source SHA-256 values matched the ledger. |
| Missing, stale or ambiguous witnesses abstain with specific reasons | **Verified in fixtures.** The installed source's focused suites passed 258 tests. The offline corpus also produced 174 instances each of missing declarations, control-map probes, native AI observations and vendor records when evaluating signals independently of the ledger guard. |
| Certified archive qualifies for human progression with payload binding, and uncertified archives are denied human authority | **Verified in fixtures.** Qualification tests exercise the positive path, changed hashes, changed witness fields, and ambiguous or missing evidence. Live positive proof remains pending. |
| One prelabelled bench with at least 6 human, 4 vendor-AI and 4 project-autonomous laps, including at least 2 vendor transitions and 1 missing or ambiguous vendor witness | **Pending.** Acceptance requires at least 5 of 6 human laps certified and zero non-human or mixed laps certified. No trial started in this continuation. The first false certification or missing hash binding fails the bench. Short counts or unavailable vendor coverage are inconclusive under the issue's rules. |
| One physical keypad declaration with ordinary shortcut behavior | **Unverified.** Earlier installed Game Point capture showed an active baseline profile and zero records after a reported Content Manager button press. The subsequent diagnostic capture had closed before the next reported press. The later 30-minute capture closed without a keypad packet or declaration. |

## Reproduction and rig state

The primary checkout was at f42f1e1fdf92f6e76472f22accc6f0762d84b591. The
installed Game Point binary hash matched the deployed #1014 receipt. The
actual CSP app junction and installed SDK's two AI/User control fields were
present. The production archive directory supplied 156 originals. The other 18
matched the ledger by exact source digest in the retained MOZA qualification
and #854 backups. A scratch-only view of the originals fed the existing
scorecard with process-scoped opt-in. The production ledger bytes were identical
before and after. The result groups into 14 existing AI and 160 existing shared
attributions. Evidence root under the primary checkout is
.scratch/issue988-integration-20261118/offline-20261121T195703Z/.
The enabled-scorecard.json SHA-256 is
b27d97bff6103729b8b6f38b8793bc3cd2bec809a673618bfac7ec9f2b4ee166.

Native Windows receiver check found one baseline keyboard, background Raw Input
registration with legacy delivery preserved, 20 successful polls and zero
remaining registrations after shutdown. Its receipt is native-registration-check.json.
No timing-coordinated physical press was captured in this continuation. All
persistent attestation and declaration environment variables were absent. The
fresh rig inventory showed no AC or active rig owner. The latest vendor snapshot
on disk was saved on 2026-10-15 UTC. The retained native archive directory had
no post-deployment lap for confirming trace.control_observation on the rig.

## Resume

With the operator at the Windows desktop, open a bounded validation-only capture
using the already installed keypad path and a disposable journal. Confirm it is
live before timing a single press and release of the existing Content Manager
button, then inspect the journal and normal shortcut. If no line is written,
use a simultaneous, keypad-filtered, read-only packet observation to distinguish
delivery from decoding and action dispatch. Close the owned collector afterward.
No wheel or pedal operation is necessary for that check.

For the remaining scored bench, coordinate one slot of at most 45 minutes with
the operator present, verify effective driving input and fresh Racing Lab vendor
coverage, confirm a new native archive carries the control observation, and
freeze the manifest before running attestation. Follow the repository bench
procedure in docs/10_Development/41_Human_Control_Attestation.md. Keep the live
producer default off outside the bench. No new issue, out-of-scope PR or agent was created.
