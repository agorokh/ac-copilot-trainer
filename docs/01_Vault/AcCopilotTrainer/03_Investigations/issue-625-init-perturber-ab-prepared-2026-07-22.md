---
type: investigation
status: superseded
memory_tier: archive
created: 2026-07-22
updated: 2026-07-28
issue: https://github.com/agorokh/ac-copilot-trainer/issues/625
superseded_by: AcCopilotTrainer/03_Investigations/issue-625-boot-scoped-redesign-2026-07-28.md
relates_to:
  - AcCopilotTrainer/03_Investigations/issue-625-boot-scoped-redesign-2026-07-28.md
  - AcCopilotTrainer/00_System/Next Session Handoff.md
  - AcCopilotTrainer/00_System/Current Focus.md
  - AcCopilotTrainer/03_Investigations/rig-freeze-csp-init-livelock-2026-07-17.md
---

# #625 init-perturber A/B — method prepared, physical run gated

> **SUPERSEDED 2026-07-28 — DO NOT RUN THE PROTOCOL ON THIS PAGE.**
> Everything below describes the **withdrawn v1 design**: one reboot, an interleaved
> single-boot schedule, a pooled per-launch freeze rate, Wilson intervals and a Fisher test.
> The #627/#668 accumulator evidence refuted the i.i.d. per-launch model that design assumes,
> so running it would put **both arms on one boot**, pool the accumulator, and return a near
> certain false negative. The live protocol is **one reboot per planned boot**; see
> [[issue-625-boot-scoped-redesign-2026-07-28]]. Kept for the record only.

Draft PR [#657](https://github.com/agorokh/ac-copilot-trainer/pull/657) adds
`tools.ac_harness.init_perturber_ab`: a seeded adjacent-pair A/B plan (20 analyzable launches per
arm), immutable `resilient-launch-report/v1` ingestion, order/uptime/summary validation, Wilson 95%
intervals, the issue-required two-sided Fisher exact test, and an exact paired sensitivity test.
`never_live` is separate and cannot complete the freeze denominator. The tool never changes Steam
or NVIDIA settings and refuses to overwrite evidence.

## Verification held

- Focused: 13 tests; ruff clean.
- Full parity: `make ci-fast` OK — 3,261 passed, 89 skipped, 83.39% coverage.
- Actual consumer path: `python -m tools.ac_harness.init_perturber_ab plan` generated commands;
  `analyze` consumed two schema-realistic reports and wrote/rendered the analysis.
- Independent oracle: local exact results matched SciPy over 1,936 Fisher tables and 120 paired
  tables.

## Live gates (2026-07-22)

The rig is physically offline. Canonical Wake-on-LAN reported `SENT`, but it did not rejoin:

```text
make windows-runner-wake
SENT: host=windows-pc wake_host=m4max-studio targets=6c:29:95:43:76:b9,70:85:c2:df:d7:1d@192.168.7.255:9

tailscale status | rg '100\.75\.251\.87'
100.75.251.87   pc   arseny.gorokh@  windows  active; relay "lax"; offline, last seen 54m ago

ssh -o BatchMode=yes -o ConnectTimeout=5 arsen@100.75.251.87 hostname
ssh: connect to host 100.75.251.87 port 22: Operation timed out
```

The remaining authorization is also live-confirmed, not inferred from an old handoff:

```text
gh issue view 625 --repo agorokh/ac-copilot-trainer --json state,body --jq ...
{"constraint":"Disabling the Steam overlay and NVIDIA ShadowPlay are operator-owned settings changes — get explicit sign-off before toggling, and restore both afterward.","state":"OPEN"}
```

This is an operator policy/hardware-state gate; there is no code symbol to anchor. Resume when the
operator powers on `pc` and explicitly authorizes toggling both settings.

**The resume steps that used to follow here have been removed** — they said "reboot once, run the
printed interleaved schedule", which is exactly the withdrawn protocol. Follow
[[issue-625-boot-scoped-redesign-2026-07-28]] instead: regenerate the plan, then apply settings and
**reboot before every one of the planned boots**.
