---
name: ac-harness
description: Launch the autonomous AC drive harness to test in-sim — car setups, dashboards, voice coaching, telemetry capture. Use whenever a task needs Assetto Corsa driven and evidence collected; never write a throwaway .scratch driver.
---

# AC autonomous harness (pointer skill)

**The canonical procedure lives in
[`docs/10_Development/18_Autonomous_Harness.md`](../../../docs/10_Development/18_Autonomous_Harness.md)
— read it now; this skill deliberately does not re-inline it** (prose-drift pitfall:
`skill-reinlines-canonical-procedure`).

What you get from the runbook:

- The **one command** (`python -m tools.ac_harness.auto_drive --car … --track … [--setup …]`)
  that owns preflight → sidecar → deterministic launch → setup apply+verify → drive →
  WS assert → evidence bundle.
- The **evidence contract** (`report.json`, `hud.png`, lap-archive paths) your task cites as
  proof — a run without its bundle is not verified.
- The **troubleshooting table** of rig lore (foreground steal, Steam elevation, Custom-AI
  enablement, single-rig contention). Consult it before debugging a failed launch.

Hard rules for agents:

1. **Issue `--preflight-only` first** when unsure the rig is ready; fix what it names.
2. **Never bypass a `stage="setup"` or `recovery cap` FAIL** by dropping the flag or raising
   the cap — those failures are the harness doing its job.
3. **One rig, one driver**: check for a live `acs.exe` / peer autonomous session and yield
   rather than contend.
4. Downstream tasks (setup A/B, dashboard, voice) **compose on the bundle**; promote anything
   durable out of `.scratch/` before session end.
