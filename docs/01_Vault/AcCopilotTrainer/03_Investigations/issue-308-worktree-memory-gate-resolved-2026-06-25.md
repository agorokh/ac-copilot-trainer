---
type: investigation
status: active
memory_tier: canonical
created: 2026-06-25
updated: 2026-06-25
relates_to:
  - AcCopilotTrainer/00_System/Next Session Handoff.md
  - AcCopilotTrainer/00_System/invariants/memory-three-tiers.md
  - AcCopilotTrainer/03_Investigations/_index.md
---

# Issue #308 — Tier-3 worktree memory-gate false-block: RESOLVED (2026-06-25)

[#308](https://github.com/agorokh/ac-copilot-trainer/issues/308) closed COMPLETED. Both acceptance
criteria verified by running the **real** SessionStart prefetch from inside a linked git worktree —
not by reading a diff.

## TL;DR for future sessions (do not re-investigate)

- The **SSRF WARN** `ignoring manifest loopback endpoint on untrusted port 8045 (not registry-known);
  SSRF guard (#7)` is **COSMETIC and BY DESIGN on a non-central host.** It is **not** a grounding
  failure. The prefetch still grounds — it reaches the substrate via the fleet registry's
  **non-loopback Tailscale HTTPS** endpoint (`https://100.71.123.90:8045`, registry-named → passes
  the allowlist), and correctly rejects the manifest's repo-controlled `http://localhost:8045`.
- If a linked-worktree session *looks* blocked, check whether the **substrate is actually reachable**
  (`verify_server_health`) before suspecting the SSRF guard — a transient outage is the usual cause.

## Part A — gitignored overlay non-propagation → fixed by #316

[PR #316](https://github.com/agorokh/ac-copilot-trainer/pull/316) (closes #314) pins
`tier3_workspace_id: ac_copilot` in the **committed** `ops/memory_manifest.yml` (tracked → present in
every worktree; the gitignored `ops/memory_manifest.local.yml` overlay is no longer needed). Verified:
prefetch in a linked worktree resolves `workspace: ac_copilot` (not `example_kb_workspace`), no
`.scratch/.last_memory_query.missing` block marker.

## Part B — prefetch SSRF guard on `:8045` → functional criterion met

Root-cause reframe: the original *"substrate unreachable → permanent SSRF block"* reading conflated a
**transient substrate outage** (502 at filing time; now up) with the **cosmetic SSRF WARN**. The SSRF
guard was never the grounding blocker. Real prefetch run from the linked worktree:

```
exit 0 · workspace: ac_copilot · result: <real grounded substrate answer>
stamp: .scratch/.last_memory_query → prefetch_ok: true · no block marker
stderr: WARN ... untrusted port 8045 (SSRF guard #7)   ← cosmetic, by design on non-central host
```

`resolve_memory_endpoints()` (governance-hub `hooks/hook_memory_manifest.py`) accepts a *loopback*
manifest endpoint only on a registry-known loopback port; on a non-central host the registry names
the workspace only at its Tailscale endpoint, so `localhost:8045` is correctly rejected. On the
central host (`mac-mini-dev`) the loopback IS registry-known → no WARN there.

## Residual (genuinely separable, upstream — filed)

The prefetch + SSRF resolver are **owned by the governance-hub**; this repo carries only thin shims.
The only thing left is downgrading the cosmetic WARN when an accepted registry endpoint already
resolved. Filed with a concrete proposed fix + acceptance criteria:
**[agorokh/governance-hub#111](https://github.com/agorokh/governance-hub/issues/111)**.
