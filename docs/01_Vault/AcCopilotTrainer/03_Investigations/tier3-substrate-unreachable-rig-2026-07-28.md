---
type: investigation
status: active
memory_tier: canonical
created: 2026-07-28
updated: 2026-07-28
issue: https://github.com/agorokh/workstation-ops/issues/2360
relates_to:
  - AcCopilotTrainer/03_Investigations/issue-719-treatment-receipt-2026-07-28.md
  - AcCopilotTrainer/00_System/invariants/memory-three-tiers.md
  - AcCopilotTrainer/00_System/Next Session Handoff.md
---

# Tier-3 is unreachable from the rig — a zombie `tailscaled`, not a slow substrate

## The correction that matters

The previous session (PR #717) recorded five `query_knowledge_graph` timeouts and concluded the
substrate was *"not unreachable, **slow past the budget**"*, recommending an infra look at LightRAG.
**That diagnosis was wrong, and the error message is why.** The bridge reports

> `query_failed: LightRAG query exceeded the bridge budget of 55s`

which reads as a slow read path. It is actually a **TCP connect that never completes**. The fault is
on the rig's network, not on the LightRAG host.

Anyone who sees that message again should probe reachability *before* looking at the substrate.

## Evidence

```
verify_server_health("ac_copilot")         -> reachable=false, https://100.84.101.4:8045/
verify_server_health("ac_copilot_trainer") -> reachable=false, same endpoint
check_indexing_status                      -> [WinError 10060] connection timed out
Test-NetConnection 100.84.101.4 -Port 8045 -> TcpTestSucceeded=False, PingSucceeded=False
```

Root cause on AG_PC: **no Tailscale adapter exists at all** (`Get-NetAdapter` matches nothing), and
`tailscaled` pid 5252 (started 2026-07-25) is a **zombie** — `Get-Process` lists it with
`HandleCount = 0` while `taskkill /F /PID 5252` answers *"There is no running instance of the task"*.
A Win32 process that has exited but whose kernel object is still referenced: the Tailscale TUN
driver is stuck, which is also why there is no adapter. The `tailscale` CLI binds to that zombie, so
every command fails with `context deadline exceeded`.

## Recovery attempted — and the reasoning for attempting it

Tailscale was **already** fully non-functional (no adapter), so restarting it could not break working
connectivity; it could only restore or leave things unchanged. That is what made it a proportionate
unattended action rather than a gamble with the operator's remote access.

1. `Restart-Service Tailscale -Force` → hung in stop-pending; the daemon never acknowledged the SCM.
2. `taskkill /F /IM tailscaled.exe` → killed pid 4276; SCM started a fresh daemon (pid 33224).
3. The zombie 5252 survived and still owns the local API socket.

Net state is functionally identical to before the attempt — service `Running`, no adapter, API
wedged. Nothing degraded; nothing fixed. **Only a reboot of AG_PC appears able to clear it**, which
is the operator's call (it also ends the agent session).

## Consequence for agents

`hook_memory_gate.py` hard-blocks every edit under `tools/`, `scripts/`, `tests/`, `ops/`. Its only
bypass, `EMERGENCY_BYPASS_GOVERNANCE=1`, is marked **human-only and audited** — and
`CLAUDE_MEMORY_GATE=0` no longer disables this gate. So an unattended agent on this rig cannot
proceed on code at all while Tailscale is down. It can still do vault/docs work, `gh` work, and rig
measurement, all of which are ungated.

That is not a reason to loosen the gate. It is a reason to make the failure legible: see
workstation-ops#2360 for the suggestion that a cheap TCP reachability probe run ahead of the
LightRAG query so "host unroutable" stops presenting as "substrate slow".

## Not the cause, but adjacent

`ops/memory_manifest.yml` pins `repo.tier3_workspace_id: "ac_copilot"`, yet both the SessionStart
hook and the gate resolved `ac_copilot_trainer` — the already-tracked bug
[#712](https://github.com/agorokh/ac-copilot-trainer/issues/712). It did **not** affect this outage:
both workspaces resolve to the same unreachable endpoint. Worth knowing so the next session does not
mistake the workspace bug for the network fault.

## Tracking

- Host/infra: [workstation-ops#2360](https://github.com/agorokh/workstation-ops/issues/2360).
- Blocked work: [#719](https://github.com/agorokh/ac-copilot-trainer/issues/719) —
  [[issue-719-treatment-receipt-2026-07-28]].
