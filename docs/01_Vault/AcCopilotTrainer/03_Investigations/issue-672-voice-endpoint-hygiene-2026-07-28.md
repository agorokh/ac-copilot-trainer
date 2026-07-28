---
type: investigation
status: active
memory_tier: canonical
created: 2026-07-28
updated: 2026-07-28
issue: https://github.com/agorokh/ac-copilot-trainer/issues/672
relates_to:
  - AcCopilotTrainer/00_System/Next Session Handoff.md
  - AcCopilotTrainer/03_Investigations/issue-602-portaudio-fixed-layout-2026-07-15.md
  - AcCopilotTrainer/03_Investigations/rig-physics-wedge-voice-wasapi-2026-07-16.md
  - AcCopilotTrainer/03_Investigations/issue-575-stale-app-junction-2026-07-15.md
---

# Issue #672 — launcher voice-endpoint hygiene (2026-07-28)

Delivered by PR [#707](https://github.com/agorokh/ac-copilot-trainer/pull/707), merge
[`1f5ce2b`](https://github.com/agorokh/ac-copilot-trainer/commit/1f5ce2b). Issue #672 CLOSED.

## What shipped

**Part A** — the own-headset invariant is now checkable. `AC_COPILOT_AC_AUDIO_DEVICE` (env) /
`ac_audio_device` (settings) declares the endpoint AC/FMOD plays through; the launcher compares it
against the sidecar's live `/health` `voice.device_name` and emits a `voice_endpoint` row in
`status.json` with **five** verdicts — `shared`, `distinct`, `undeclared`, `unknown` (voice not
running), `unverifiable` (running, but the backend reports no device). `shared` paints the Voice row
amber `SHARED_ENDPOINT`; `unverifiable` paints it amber `ENDPOINT_UNVERIFIED`. Every verdict is
`ok=True` — the rig ships deliberately pinned to the shared endpoint, so this must never block START.

**Part B** — `voice_bank_source` records whether the resolved bank came from env or settings, shown
on the Voice row and in `status.json`. Set-but-blank env (which *parks* voice) is now diagnosable.

## The thing worth remembering: the fixtures were lying

Everything below was invisible to a green test suite and surfaced only by running the real thing.

1. **The feature was inert in the product's own entrypoint.** `config_from_args` rebuilds
   `GamePointConfig` field-by-field, so both new fields were silently dropped. With the env var
   exported, real `python -m tools.rig_launcher --once` still said `undeclared`. Now guarded
   generically: a test asserts *every* dataclass field survives the rebuild.
2. **PortAudio reports one endpoint four ways.** Measured here, one physical device:
   MME `'5.1 Speakers (USB Sound Device '` (truncated to 31 incl. trailing space), WASAPI and
   DirectSound `'5.1 Speakers (USB Sound Device        )'` (internal padding), WDM-KS
   `'Speakers (USB Sound Device)'` (drops the `5.1 `). The operator types what Windows shows them.
   Any normalization not built from these strings gets it wrong.
3. **`.strip()` on the health device name defeated the truncation rule** — 31 chars → 30, so the
   live poll said `distinct` while the matcher unit test passed on an unstripped fixture. Layer
   tests that assert through `poll_status`, not through the matcher.

## Review: 5 Codex rounds, 8 P2s, all real

No finding was rejected. The arc is the interesting part — each round attacked the *soundness* of
the prefix heuristic, and the rule converged from a guess to an exact signature:

| round | defect | fix |
|---|---|---|
| 1 | 8-char prefix floor let generic `Speakers` collide | gate on the MME truncation boundary |
| 2 | `>=31` let two distinct long endpoints collide; test was symmetric | `==31`, one-directional (health side only) |
| 2 | `.strip()` on the health device name (above) | return verbatim |
| 2 | blank env bank leaked into the child env | `_put_or_clear` |
| 3 | 31 chars alone ≠ truncated | also require the MME host API |
| 3 | exact-case `pop` vs `_CaseInsensitiveEnv` | case-insensitive clear |
| 3 | TTS backend reports no device → check silently inoperative | split `unknown` / `unverifiable` |
| 4 | deleting all whitespace erased meaningful separators | collapse runs; drop only padding at punctuation |

Round 3's TTS split reuses the **#575 precedent**: "unknown" was hiding two states with opposite
risk profiles, so it was split rather than widened. Same move, same reason.

## Known limitation (pinned, not papered over)

WDM-KS drops the `5.1 ` prefix, so that spelling reads `distinct` against the declared name. Not
fixed with a suffix rule — that would widen the false-positive surface for a host API the voice
stack does not use (#602 resolves voice on WASAPI). The `distinct` detail prints **both** names, so
a normalization miss is self-diagnosing from the row.

## Still operator-gated

Voice re-arm on the rig, and any soak with voice armed, remain gated under #627 — this shipped
warning/visibility code only. The `shared`/`distinct` verdicts were proven against the rig's real
device strings and the real launcher process, with `/health` stood in rather than an armed stream.

## Fleet fact worth carrying

The **self-hosted reviewer daemon now reviews this repo** — Phase-2 consolidated (`cursor` +
`grok`, `EPIC #818 P5`), zero findings ≥ medium on the final two SHAs. Prior vault notes saying
"self-hosted daemon does not review this repo (gate vacuous)" are **stale**; do not carry that
forward.

Also: `make ci-fast` was red on Windows before any of this work — a `Path("C:/repo\\")` fixture
that only POSIX can keep a trailing backslash on. Owned and fixed here rather than deferred.
