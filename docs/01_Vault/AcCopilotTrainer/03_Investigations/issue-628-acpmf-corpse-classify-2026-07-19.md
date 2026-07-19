---
type: investigation
status: active
memory_tier: canonical
created: 2026-07-19
updated: 2026-07-19
issue: https://github.com/agorokh/ac-copilot-trainer/issues/628
relates_to:
  - AcCopilotTrainer/03_Investigations/rig-freeze-csp-init-livelock-2026-07-17.md
  - AcCopilotTrainer/00_System/Next Session Handoff.md
source_path: "AcCopilotTrainer/03_Investigations/issue-628-acpmf-corpse-classify-2026-07-19.md"
workspace: "ac_copilot"
---

# #628 — the launcher was discarding healthy sessions; the `acpmf` corpse hands over into the new `acs` lifetime

Surfaced while executing #627 §1 Step 1 (measure the baseline freeze rate on the repaired rig).
PR [#629](https://github.com/agorokh/ac-copilot-trainer/pull/629).

## The headline

The rig was **not** as broken as it looked. A large share of what read as "the rig cannot launch"
was `resilient_launch.classify()` throwing away **healthy, normally-loading sessions** as
`never_live` in ~8 s. Every retry after the first burned an attempt on a phantom, so the merged
retry launcher (#624 / PR #626) could never demonstrate the recovery it exists to provide.

## Mechanism (measured, not inferred)

`acpmf_*` is a shared section that outlives its creator — it stays mapped while any other process
holds a handle. `.scratch/debris_probe.py --kill`:

```
hard-killing acs.exe ... acs.exe gone at t+0
[t+0s ] physics=PRESENT graphics=PRESENT static=PRESENT
[t+14s] physics=PRESENT graphics=PRESENT static=PRESENT
```

The subtle part — and why a liveness guard alone does not fix it — is that the corpse survives
**into the next process's lifetime**. `.scratch/trial_verbose.py`:

```
   0.0    None    16983   <- corpse, acs absent
   2.0   14020    16983   <- new acs ALIVE and loading, section STILL the corpse
   6.0   14020    16983
   8.0   14020      121   <- new session finally publishes -> REGRESSED -> never_live
```

For ~6 s the readings are stale *and* live-correlated. When the real stream appears at a low packet
id it reads as a regression, and the launch is discarded.

**Fix:** before go-live a regression is a hand-over, not a failure — rebase on the new stream and
let the go-live timeout be the only pre-live failure. The post-go-live guard is unchanged.

This is trap #627 §7.1 ("shared-memory corpses outlive `acs.exe`") reaching the **shipped verdict
logic**, not just the ad-hoc probes. The trap was known; that it had contaminated production code
was not.

## The second corpse bug — and why only the shipped path could reveal it

The packet-id fixes above made `.scratch/capture_freeze.py` report **8/8 stable**. The real command
an operator runs then failed **6/6 attempts in ~7 s each**, every one recorded as `froze`:

```
attempt 1: froze   attempt 2: froze   attempt 3: froze
attempt 4: froze   attempt 5: froze   attempt 6: froze
no stable session in 6 attempt(s) (froze 6, never_live 0)
```

`read_state()` returns `graphics.is_live and not graphics.is_in_pit` with **no acs.exe
correlation**. Those flags live in the same section as the packet id and are exactly as stale, so
the corpse reports the session READY before AC has started. `read_attempt_state` fires the Car0
drivability handshake on the first `entry_ready is True`; it failed against a session that did not
exist and raised `_Car0NotDrivable`, which the launcher records as a freeze.

The bespoke driver could never see this — **it does not perform the Car0 handshake.** A measurement
harness that skips a step the product performs will certify a product that does not work.

**Generalised fix:** no shared-memory reading is trustworthy until the live `acs.exe` is proven to
**own** the section, and process liveness alone does not prove it (the corpse survives into the new
process's lifetime). Ownership is proven only when the packet id **advances while acs.exe is
alive**. Extracted as `SectionOwnershipGate` so the rule is unit-testable instead of buried in a
closure inside the rig-only `main()`.

**Verified on the unmodified deliverable path:** `stable drivable session held on attempt 1
(froze 0, never_live 0) — AC left LIVE`, with shared memory showing ~105 fps (`gfx` +210 per 2 s)
and physics advancing, released via the sentinel rather than a taskkill. Screenshot inspected: live
cockpit at Spa-Francorchamps with the `T1 SPA` dashboard and COACHING tiles rendering.

## Final design after review (PR #629, 6 review rounds)

The ownership rule went through several sharpenings under qodo + the self-hosted daemon, and the
converged design is *simpler* than any intermediate — the review pressure drove it to the right
invariant:

**A packet id can only advance if a live process wrote it.** A corpse is a frozen snapshot; it
never advances on its own. So packet advancement is itself the proof of a live owner, and **no
process-liveness probe is needed in the sampling loop at all.**

- **`SectionOwnershipGate`** consults ONLY the packet stream: an advance grants trust, a regression
  (a new generation — the same signal `classify` uses post-go-live) revokes it.
- **`AttemptReadiness`** owns the gate plus the one-shot Car0 handshake cache, revoked together, so
  a replacement session cannot inherit the dead generation's `car0_ready`.
- **One liveness signal, not two.** `classify` ends the attempt on real death via the DEBOUNCED
  `Sample.acs_alive` (`_ResettableProcessLivenessProbe`, `absent_confirmations=2`). The sampling
  loop no longer consults any process probe, so there is nothing for that debounced signal to
  disagree with.

The intermediate designs that consulted a strict `acs_present()` probe each drew a review finding —
strict-vs-debounced *tearing* (HIGH), a single strict miss *revoking* trust (MEDIUM), and an
enumeration OSError coerced to a None sample that *corrupted classify's stall run* (HIGH). All three
dissolved once the probe was removed: the corpse-safety property reduces to one sentence — Car0
fires only when publishing, publishing requires an advance, a corpse cannot advance.

92 off-rig tests. The advisory antigravity HIGH ("feed the strict probe into classify") is moot —
there is no strict probe in the path anymore.

## Live proof at higher uptime

The final verification ran at ~2.7 h uptime and, for the first time this session, hit the **real**
CSP freeze: the launcher retried past **four genuine `froze` attempts** and held a stable drivable
session on attempt 5 — AC left LIVE, ~98 fps with physics advancing. That is the launcher's whole
purpose (retry past the #619 livelock) demonstrated end to end against the actual bug — not a clean
1/1, but the harder and more convincing evidence.

**Follow-on now unblocked:** freezes are reproducible at this uptime, so `.scratch/soak.py` +
`.scratch/freeze_forensics.py` can finally catch a *real* wedge and settle #627 §6.1 (spin vs block
vs long computation). That is the next rig session's first task.

## Measured result (#627 §1 Step 1)

With the fix, 8 consecutive launches, Porsche 911 GT3 R @ Spa, uptime 2.144 → 2.456 h:

**n=8, stable 8, froze 0, never_live 0.** Artifact
`.scratch/freeze-forensics/baseline-20260719-101614.json`. Trial elapsed times clustered tightly at
150.7–164.9 s (the 140 s stability window plus load).

Contrast with the same driver *before* the fix: 6 trials → 1 stable, 1 "froze" (actually a transient
stall, see below), 4 × `never_live` in a near-identical **8.1 s** — the corpse signature.

**This is not evidence the freeze is fixed**, and must not be quoted as such:

- §7.6 applies — the rig was rebooted at 08:10 for the operator's repair, and this whole window is
  at 2.1–2.5 h uptime, the regime §3.4 calls low-rate. Never credit a fix that followed a reboot.
- The driver hard-kills `acs` between trials (§6.5 — the flaw this brief flags in `ab_runner.py`).
- The init wedge would be bucketed `never_live`, not `froze` (#630 Part C), so this is really a
  "not-stable rate of 0/8", not a freeze rate.

## Corrections to the #627 master brief

| #627 says | Reality (2026-07-19) |
|---|---|
| §8: "PR #626 (draft) … still needs a green rig verification" | **MERGED** `37a0189`, 2026-07-19T13:23:59Z; issue #624 CLOSED |
| §3.5: thread 0 spinning in a "tight integer **hash** loop (mod-512, outer bound 9, `imul …147Bh`)" | `0x147B` is **not** a hash multiplier. It is the compiler's reciprocal magic for **division by 100**: `imul ebx,eax,0x147B / shr ebx,0x11 / imul eax,ebx,-0x64 / add edx,eax` == `divmod 100`. The enclosing function is **base-100 arbitrary-precision limb arithmetic** — Dragon4-style float→decimal conversion — with `and r,0x1ff` as a 512-limb ring and `cmp r11d,9` as a limb count. Number formatting, not hash-bucket probing. |

The `0x147B` identification was verified independently: exactly two `imul r32,r32,0x147B` sites in
the whole 121 MB image (RVA `0x014e7110`, `0x014e7156`), both inside one `RUNTIME_FUNCTION`
(`0x014e6db0`–`0x014e7355`), and `((x>>2)*5243)>>17 == x//100` holds for all x < 174796.

**Open caveat — do not build on the RIP attribution.** The dump's wedged RIP is quoted as
`dwrite.dll+0x1391C02`, but `0x7fffc9d6fe42 − 0x1391C02 = 0x7FFFC89DE240`, which is not
page-aligned and therefore cannot be a module base. Hand-decoding the on-disk bytes at RVA
`0x1391C02` shows a recursive-doubling loop with calls (`mov edi,80h` / `cmp rsi,rdi` /
`add rdi,rdi`), **not** the `imul 0x147B` divmod site and no `add edx,eax`. So §3.5 conflates at
least two things. The *constant's* meaning is settled; *where the wedge actually sits* is not.

## New instrument: spin-vs-block in 5 s, no dumps — but §6.1 is NOT yet answered

`.scratch/freeze_forensics.py`. `QueryThreadCycleTime` per thread should answer the question two
4.8 GB dumps were being proposed for: a blocked thread accrues ~0 cycles, a spinning one accrues ~a
full core.

**It has not yet been fired at a real wedge.** The one capture on 2026-07-19 10:03 was a
**false alarm, and I initially misread it as a confirmed spin.** The saved verdict
(`verdict-20260719-100321.json`) records:

```
s3_gfx_packet : [23, 4233]     <- the render packet ADVANCED during the diagnosis
s3_gfx_static : False
verdict       : INCONCLUSIVE
s1_hot_thread : {'tid': 14852, 'cycles_per_s': 2.85e9}
s1_thread_count: 67
```

The session **recovered**: `classify` saw 4 consecutive unchanged samples during load and returned
`FROZE`, but the session then rendered on to packet 4233. So that trial was a **transient load
stall misclassified as a freeze** (see #630 Part B), not a wedge.

And `s1_burning_cpu=True` is **not evidence of a livelock on its own** — a healthy 67-thread AC
rendering at ~100 fps burns a full core by design. The cycle signal is only meaningful when
`gfx_static` is simultaneously true. The tool's own final verdict was correctly `INCONCLUSIVE`; I
read the intermediate log line `S1: … BURNING CPU (spin)` as if it were the conclusion.

**Status: #627 §6.1 (spin vs block vs long computation) remains OPEN.** The only genuine wedge
evidence is still the historical dump. The instrument is built and validated but has not yet caught
a real one.

## Method lessons (these cost real time today)

1. **Validate the instrument against known ground truth before believing it.** The first version of
   the cycle sampler read **0 cycles/s on a deliberate spinner**. The Win32 code was correct; the
   *test target* was wrong — `.venv\Scripts\python.exe` is a shim that re-spawns the real
   interpreter as a child, so it was sampling a parked launcher. Had I trusted it, I would have
   concluded "BLOCKED, not a spin" — the exact opposite of the truth.
2. **`~0s` in cdb selects thread *index* 0, not the busy thread.** In `acs.exe` index 0 is parked in
   an ntdll wait while the spinner is elsewhere, so RIP samples looked like they wandered across
   gigabytes. Target the hot TID (`~~[0xTID]s`).
3. **A verdict path that can fire on insufficient data will fire.** With only one successful RIP
   read the tool fell through to `LONG_COMPUTATION` and printed "RIP wanders" — from a single
   sample, which contains no information about wandering. That is the one verdict that would have
   wrongly killed the livelock hypothesis. Now `INCONCLUSIVE_INSUFFICIENT_RIP_SAMPLES`.
4. **A stray CPU-burner perturbs the rig.** A runaway `sim.py` from a subagent was burning a full
   core during trial 1 of the first run. Check for unexpected load before trusting any rate.
5. **I rebuilt the flaw I had just criticised.** #627 §6.5 warns that `ab_runner.py` hard-kills
   `acs` between trials and may itself degrade the rig — and my measurement driver does exactly the
   same thing. Any rate measured this way carries that caveat.
6. **A bespoke measurement harness can certify a broken product.** `capture_freeze.py` said 8/8
   stable while the shipped launcher failed 6/6, because the harness skipped the Car0 handshake the
   product performs. Measure the mechanism with a harness if you must, but the completion evidence
   has to come from the deliverable's own unmodified path.

## Status of the freeze itself

Unchanged and still third-party: the CSP init wedge (#619/#625) is not fixed here and cannot be
fixed from this repo. What changed is that the harness can now **measure and survive** it, and the
spin-vs-block question has a decisive answer.
