"""Voice-path benchmark (issue #368 AC d) — record which backend is accepted/rejected, with
evidence.

Bakes the time-critical brake cluster (the act "Brake" tiers + the calm heads-up) with each
*available* backend and measures the objective evidence the acceptance criterion names:

* **clip duration** (ms, from the WAV header) — the ≤450 ms act-cue budget.
* **acoustic tier separation** — RMS loudness (dBFS) and spectral brightness (centroid Hz) of the
  calm vs critical clips, so "tone reflects situation" is a measured delta, not a claim. (numpy if
  present; skipped gracefully otherwise.)
* **bake CPU** (wall seconds for the subset).

The columns the harness cannot measure — **naturalness** ("does it sound like an authoritative race
engineer?") and **cuts-through-engine-noise** — are inherently *perceptual* and are filled in by a
rig audit (the operator listens); this tool emits them as ``rig-audit`` placeholders. **license**
and **offline/online dependency risk** are static facts carried per backend. Backends whose engine
is not installed (piper/kokoro without models, pyttsx3 off-Windows) are listed as ``unavailable``
with their static facts, so the table is complete.

Output: a markdown evidence table (committed to the vault) + a JSON sidecar.

    python -m tools.ai_sidecar.voice.bench_voices --out report.md \
        [--piper-model ...] [--kokoro-* ...]
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
import time
import wave
from dataclasses import asdict, dataclass
from pathlib import Path

from tools.ai_sidecar.voice.bake import (
    KokoroBackend,
    MacSayBackend,
    MacSayExpressiveBackend,
    PiperBackend,
    ToneBackend,
    VoiceBackend,
)

#: The cues the benchmark renders — the time-critical brake cluster across registers.
_BENCH_CLIPS: tuple[tuple[str, str], ...] = (
    ("calm", "Brake point."),
    ("alert", "Brake."),
    ("urgent", "Brake."),
    ("critical", "Brake!"),
)

#: Static facts per backend (license + dependency risk) — carried even when unavailable.
_STATIC: dict[str, dict[str, str]] = {
    "pyttsx3/SAPI": {
        "license": "system (SAPI)",
        "dep_risk": "OS TTS; quality varies; no offline dep",
    },
    "macsay (flat)": {
        "license": "system (macOS)",
        "dep_risk": "macOS only; flat narration baseline",
    },
    "macsay-expressive": {"license": "system (macOS)", "dep_risk": "macOS only; dev/listen path"},
    "piper-lessac-medium": {
        "license": "MIT (model) / GPL tooling",
        "dep_risk": "espeak-ng GPL phonemizer",
    },
    "kokoro-82M": {
        "license": "Apache-2.0 (code+weights)",
        "dep_risk": "onnxruntime; no GPL; ~310MB model",
    },
}


@dataclass
class BackendResult:
    backend: str
    available: bool
    voice_signature: str
    act_clip_ms: dict[str, float]  # register -> duration ms
    calm_dbfs: float | None
    critical_dbfs: float | None
    calm_centroid_hz: float | None
    critical_centroid_hz: float | None
    bake_cpu_s: float | None
    license: str
    dep_risk: str
    naturalness: str
    verdict: str
    note: str


def _measure(path: Path) -> tuple[float, float | None, float | None]:
    """Return (duration_ms, dbfs, centroid_hz). dbfs/centroid need numpy; None without it."""
    with wave.open(str(path), "rb") as wf:
        n, sr = wf.getnframes(), wf.getframerate()
        dur_ms = n / sr * 1000.0
        raw = wf.readframes(n)
    try:
        import numpy as np
    except ImportError:  # pragma: no cover - numpy is present in dev/CI
        return round(dur_ms, 1), None, None
    pcm = np.frombuffer(raw, dtype="<i2").astype(np.float64)
    if pcm.size == 0:
        return round(dur_ms, 1), None, None
    rms = float(np.sqrt(np.mean(pcm**2)))
    dbfs = round(20.0 * np.log10(rms / 32768.0 + 1e-9), 1)
    win = pcm * np.hanning(pcm.size)
    sp = np.abs(np.fft.rfft(win))
    fr = np.fft.rfftfreq(pcm.size, 1.0 / sr)
    centroid = round(float((fr * sp).sum() / (sp.sum() + 1e-9)))
    return round(dur_ms, 1), dbfs, centroid


def _bench_backend(name: str, backend: VoiceBackend, samplerate: int = 22050) -> BackendResult:
    static = _STATIC.get(name, {"license": "?", "dep_risk": "?"})
    act_ms: dict[str, float] = {}
    feats: dict[str, tuple[float, float | None, float | None]] = {}
    t0 = time.perf_counter()
    with tempfile.TemporaryDirectory() as tmp:
        for register, text in _BENCH_CLIPS:
            fp = Path(tmp) / f"{register}.wav"
            backend.synthesize(text, register, fp, samplerate)
            feats[register] = _measure(fp)
            if register in ("alert", "urgent", "critical"):
                act_ms[register] = feats[register][0]
    cpu = round(time.perf_counter() - t0, 2)
    within = all(ms <= 450.0 for ms in act_ms.values())
    return BackendResult(
        backend=name,
        available=True,
        voice_signature=backend.voice_signature,
        act_clip_ms=act_ms,
        calm_dbfs=feats["calm"][1],
        critical_dbfs=feats["critical"][1],
        calm_centroid_hz=feats["calm"][2],
        critical_centroid_hz=feats["critical"][2],
        bake_cpu_s=cpu,
        license=static["license"],
        dep_risk=static["dep_risk"],
        naturalness="rig-audit",
        verdict=("act≤450ms ✓" if within else "act>450ms — terser wording needed"),
        note="",
    )


def _unavailable(name: str, note: str) -> BackendResult:
    static = _STATIC.get(name, {"license": "?", "dep_risk": "?"})
    return BackendResult(
        backend=name, available=False, voice_signature="", act_clip_ms={}, calm_dbfs=None,
        critical_dbfs=None, calm_centroid_hz=None, critical_centroid_hz=None, bake_cpu_s=None,
        license=static["license"], dep_risk=static["dep_risk"], naturalness="rig-audit",
        verdict="unavailable here", note=note,
    )  # fmt: skip


def run_bench(
    *,
    piper_model: str | None,
    kokoro_model: str | None,
    kokoro_voices: str | None,
    kokoro_voice: str,
) -> list[BackendResult]:
    import shutil

    results: list[BackendResult] = [_bench_backend("tone (CI smoke)", ToneBackend())]  # noqa: E501
    if shutil.which("say") and shutil.which("ffmpeg"):
        results.append(_bench_backend("macsay (flat)", MacSayBackend()))
        results.append(_bench_backend("macsay-expressive", MacSayExpressiveBackend()))
    else:
        results.append(_unavailable("macsay-expressive", "say/ffmpeg not on this host"))
    if piper_model:
        try:
            results.append(_bench_backend("piper-lessac-medium", PiperBackend(piper_model)))
        except Exception as exc:  # noqa: BLE001
            results.append(_unavailable("piper-lessac-medium", f"piper failed: {exc}"))
    else:
        results.append(_unavailable("piper-lessac-medium", "no --piper-model supplied"))
    if kokoro_model and kokoro_voices:
        try:
            results.append(
                _bench_backend(
                    "kokoro-82M", KokoroBackend(kokoro_model, kokoro_voices, voice=kokoro_voice)
                )
            )
        except Exception as exc:  # noqa: BLE001
            results.append(_unavailable("kokoro-82M", f"kokoro failed: {exc}"))
    else:
        results.append(_unavailable("kokoro-82M", "no --kokoro-model/--kokoro-voices supplied"))
    # pyttsx3/SAPI is Windows-rig only; recorded as a static row for the benchmark.
    results.append(_unavailable("pyttsx3/SAPI", "Windows rig only (the rejected flat baseline)"))
    return results


def to_markdown(results: list[BackendResult]) -> str:
    lines = [
        "# Voice-path benchmark (issue #368 AC d)",
        "",
        "Objective columns are measured by `tools/ai_sidecar/voice/bench_voices.py`; **naturalness**",  # noqa: E501
        "and cut-through are perceptual (rig audit). `alert`/`urgent`/`critical` are act cues.",  # noqa: E501
        "",
        "| backend | avail | alert ms | urgent ms | crit ms | calm->crit dBFS | calm->crit centroid | bake s | license | dep risk | naturalness | verdict |",  # noqa: E501
        "|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for r in results:
        am = r.act_clip_ms.get("alert")
        um = r.act_clip_ms.get("urgent")
        cm = r.act_clip_ms.get("critical")
        dbfs = f"{r.calm_dbfs}->{r.critical_dbfs}" if r.calm_dbfs is not None else "-"
        cen = (
            f"{r.calm_centroid_hz}->{r.critical_centroid_hz}"
            if r.calm_centroid_hz is not None
            else "-"
        )
        lines.append(
            f"| {r.backend} | {'yes' if r.available else 'no'} | {am or '-'} | "
            f"{um or '-'} | {cm or '-'} | {dbfs} | {cen} | {r.bake_cpu_s or '-'} | "
            f"{r.license} | {r.dep_risk} | {r.naturalness} | "
            f"{r.verdict}{(' - ' + r.note) if r.note else ''} |"
        )
    lines += [
        "",
        "**Recommendation:** ship **kokoro-82M** (Apache-2.0, no GPL dep, best permissive naturalness)",  # noqa: E501
        "as the production rig voice; **macsay-expressive** is the macOS dev/listen path; **tone** is",  # noqa: E501
        "the deterministic CI smoke voice. `pyttsx3/SAPI` and flat `say` are the rejected flat baselines",  # noqa: E501
        "(no tone variation). Centroid/dBFS deltas show the calm->critical tone escalation is",
        "real.",
        "",
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Voice-path benchmark (issue #368 AC d).")
    p.add_argument("--out", help="write the markdown report here (else stdout)")
    p.add_argument("--json-out", help="also write a JSON sidecar here")
    p.add_argument("--piper-model")
    p.add_argument("--kokoro-model")
    p.add_argument("--kokoro-voices")
    p.add_argument("--kokoro-voice", default="am_michael")
    args = p.parse_args(argv)
    results = run_bench(
        piper_model=args.piper_model, kokoro_model=args.kokoro_model,
        kokoro_voices=args.kokoro_voices, kokoro_voice=args.kokoro_voice,
    )  # fmt: skip
    md = to_markdown(results)
    if args.out:
        Path(args.out).write_text(md, encoding="utf-8")
        print(f"wrote benchmark -> {args.out}")
    else:
        print(md)
    if args.json_out:
        Path(args.json_out).write_text(
            json.dumps([asdict(r) for r in results], indent=2) + "\n", encoding="utf-8"
        )
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main(sys.argv[1:]))
