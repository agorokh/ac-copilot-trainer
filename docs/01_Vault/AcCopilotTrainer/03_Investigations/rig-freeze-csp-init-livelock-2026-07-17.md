---
type: investigation
status: active
memory_tier: canonical
created: 2026-07-17
updated: 2026-07-17
issue: https://github.com/agorokh/ac-copilot-trainer/issues/619
relates_to:
  - AcCopilotTrainer/03_Investigations/rig-freeze-csp-loop-2026-07-16.md
  - AcCopilotTrainer/00_System/Next Session Handoff.md
supersedes: AcCopilotTrainer/03_Investigations/rig-freeze-csp-loop-2026-07-16.md
---

# #619 root cause: stochastic infinite loop inside CSP 0.2.4 at session init (dump-proven)

## Verdict (high confidence — direct dump evidence)

The rig freeze is a **CPU-bound spin / infinite loop (livelock) on AC's main thread inside
Custom Shaders Patch 0.2.4** (`accRenderingAdv.dll`, which loads as the game-folder `dwrite.dll`
proxy), hit **during session init**. It is **stochastic per launch** (a coin-flip). A session
that survives the first ~90–120 s runs **indefinitely**.

## Evidence

- **Dump (acs wedged, 89 s uptime, mid session-load):** thread 0 RIP on `add edx,eax` inside a
  tight nested integer hash/scramble loop (mod-512 index, outer bound 9, `imul …147Bh`). A thread
  cannot be *waiting* with RIP on an arithmetic op → **spin, not lock, not GPU wait**. 13 CSP
  frames above `acs.exe` game code; real MS DirectWrite is a separate module, not on thread 0.
  All 69 other threads (NVIDIA UMD pool, physics, FMOD, DXGI) are idle-parked — idle because the
  main thread never returns, not blocked.
- **OS-invisible** (event logs, 30 days): no TDR/nvlddmkm 4101, no WHEA, no Application-Hang 1002,
  no crash/WER for acs.exe. Not a driver reset, not hardware.
- **GDI/USER exhaustion REFUTED** by live sampling: acs GDI flat at **51/10000**, USER ~29, total
  handles ~890 during a live run; system-wide GDI ~1287. No leak. (Was the web/council #1 guess.)
- **Once-live = stable:** an instrumented survivor ran 7+ min live, GDI flat, never wedged
  (`.scratch/catch_freeze.log`). Freezes only ever occur at/near init (~48–90 s), never observed
  after a session was stably live for minutes.

## What was NOISE (corrected)

"KB5095132 fixed it", "time-since-boot degradation", "acs-kill-count degradation" — all
small-sample artifacts. Each reboot/change happened to precede a lucky streak of the per-launch
coin-flip. The `ab_runner.py` A/B hard-kills acs between trials, which added variance and
manufactured trend illusions. The real variable is **per-launch stochastic init convergence**.

## Solution

- **Reliable playability (engineering fix around a third-party bug):** `.scratch/play_until_stable.py`
  — retry the launch until a session survives a ~150 s stability window, then hand off. Works
  because once-live is stable. (Verify it delivers before claiming solved.)
- **Real fixes:** (1) upstream CSP bug report — `accRenderingAdv.dll` mod-512 hash loop at
  RIP `+0x516f52`, spins with a data-dependent exit that occasionally never converges; (2) try a
  **different CSP build** (0.2.4 = 2024; loop may be version-specific; 0.2.11 only n=1 tested);
  (3) test removing injected init-perturbers (Steam overlay, NVIDIA ShadowPlay `nvspcap64`) or
  trimming the dashboard app's init footprint to lower the per-launch freeze probability.

## Durable method lessons

- **Read the dump's module list before trusting frame names:** `dwrite.dll` in a game folder is
  CSP, not Windows DirectWrite. A misread of this cost ~a day.
- **RIP on an arithmetic op = spin; RIP on a syscall/wait = block.** That one register settled
  spin-vs-deadlock definitively where `!analyze`/`!locks` (broken by missing ntdll symbols) could not.
- **Never attribute an intermittent, stochastic failure from n≤4.** Quantify a *rate* with many
  trials before believing any "fix". Reboots/edits that precede a lucky streak masquerade as fixes.
- **Measure the leading hypothesis before chasing it:** GDI exhaustion was the unanimous
  expert/web guess and was false in one live sample.
- Tooling worth keeping: `ab_runner.py` (packetId freeze judge), `gdi_sampler.py` (GetGuiResources),
  `catch_freeze.py` (live-frozen snapshot + dump, keeps acs alive), `monitor_degradation.py`.
