"""The phrase-bank **manifest** — the single, content-addressed advisory->audio mapping.

A baked bank is a directory of WAV clips plus a ``manifest.json`` that maps every
``(kind, urgency, corner)`` advisory key to a clip file. The manifest is the *only* place an
advisory turns into audio (issue #340): the resolver reads it, nothing hardcodes wording->file in
Python.

It is **content-addressed** so wording/voice drift is *detected*, never silently stale (the
canonical damage the issue cites — PR #38/#35, a persistence step that silently never ran):

* ``vocabulary_hash`` — :func:`tools.ai_sidecar.voice.vocabulary.vocabulary_hash` at bake time.
  If the wording set later changes without a re-bake, load detects the mismatch and the engine
  degrades
  (logs loudly, maps nothing) rather than speaking a stale phrase.
* per-clip ``sha256`` — of the WAV bytes, so a corrupted/truncated/substituted clip is caught at
  validation, not at the wheel.

Pure stdlib (``json`` + ``hashlib`` + ``wave`` are all stdlib). No audio dependency is needed to
*load and validate* a manifest — only to *play* the clips it points at.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

from tools.ai_sidecar.voice import vocabulary as vocab

#: Manifest schema version. Bump on any breaking change to the on-disk shape.
#: v2 (issue #368): adds ``register`` (intensity tier) to every clip + the index key.
#: v3 (issue #381): changes canonical register values from calm/firm/critical to
#: calm/alert/urgent/critical and folds persona/intensity-chain metadata into voice_signature.
MANIFEST_VERSION = 3

#: Canonical manifest filename inside a bank directory.
MANIFEST_FILENAME = "manifest.json"


class ManifestError(Exception):
    """A manifest could not be parsed or is structurally invalid (a *hard* load failure).

    Distinct from a *content* mismatch (stale vocabulary hash, missing clip file, sha mismatch) —
    those are reported by :meth:`Manifest.validate` so the engine can degrade gracefully per clip,
    rather than crashing.
    """


@dataclass(frozen=True)
class ClipEntry:
    """One manifest row: an advisory key and the bank clip that serves it."""

    clip_id: str
    file: str  # relative to the bank directory
    kind: str
    urgency: str
    register: str  # intensity tier (calm|alert|urgent|critical) — issue #381, v3 manifest
    corner: int | None
    text: str
    sha256: str

    def to_dict(self) -> dict:
        return {
            "clip_id": self.clip_id,
            "file": self.file,
            "kind": self.kind,
            "urgency": self.urgency,
            "register": self.register,
            "corner": self.corner,
            "text": self.text,
            "sha256": self.sha256,
        }

    @staticmethod
    def from_dict(d: dict) -> ClipEntry:
        try:
            corner = d["corner"]
            if corner is not None:
                corner = int(corner)
            # ``register`` is REQUIRED in v2: a v1 manifest (no register) raises here at LOAD, so
            # ``engine.from_bank`` returns a disabled coach rather than ever playing a clip whose
            # tier is unknown (issue #368). No lenient default — that would let an old bank
            # masquerade as current. The value is also validated against the allowed tiers at
            # load so a hand-edited/corrupt manifest fails loudly here, not as a silent lookup miss
            # later (codex/qodo review #371).
            register = vocab.normalize_register(d["register"])
            if register not in vocab.REGISTERS:
                raise ValueError(f"register {register!r} not in {vocab.REGISTERS}")
            return ClipEntry(
                clip_id=str(d["clip_id"]),
                file=str(d["file"]),
                kind=str(d["kind"]),
                urgency=str(d["urgency"]),
                register=register,
                corner=corner,
                text=str(d["text"]),
                sha256=str(d["sha256"]),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ManifestError(f"malformed clip entry: {d!r} ({exc})") from exc


@dataclass(frozen=True)
class ValidationReport:
    """Outcome of :meth:`Manifest.validate` — empty ``problems`` means a clean bank."""

    vocabulary_matches: bool
    problems: list[str]

    @property
    def ok(self) -> bool:
        return self.vocabulary_matches and not self.problems


@dataclass
class Manifest:
    """A loaded phrase-bank manifest with a fast ``(kind, urgency, corner) -> clip_id`` index."""

    version: int
    samplerate: int
    voice_signature: str
    vocabulary_hash: str
    clips: dict[str, ClipEntry]

    def __post_init__(self) -> None:
        # Index by advisory key for O(1) resolver lookups. ``corner=None`` is the generic/terse
        # clip. ``register`` (issue #368) is the 3rd key axis — the intensity tier.
        self._by_key: dict[tuple[str, str, str, int | None], str] = {}
        for entry in self.clips.values():
            self._by_key[(entry.kind, entry.urgency, entry.register, entry.corner)] = entry.clip_id

    def lookup(self, kind: str, urgency: str, register: str, corner: int | None) -> str | None:
        """Return the clip id for an advisory key, or ``None`` if the bank has no such clip."""
        return self._by_key.get((kind, urgency, vocab.normalize_register(register), corner))

    # ---- (de)serialization -------------------------------------------------------------------

    def to_dict(self) -> dict:
        return {
            "version": self.version,
            "samplerate": self.samplerate,
            "voice_signature": self.voice_signature,
            "vocabulary_hash": self.vocabulary_hash,
            "clips": {cid: e.to_dict() for cid, e in sorted(self.clips.items())},
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, ensure_ascii=True, sort_keys=False) + "\n"

    @staticmethod
    def from_dict(d: dict) -> Manifest:
        if not isinstance(d, dict):
            raise ManifestError("manifest root is not an object")
        try:
            version = int(d["version"])
            # Version is an authoritative schema gate (issue #368): a bank written by a different
            # schema than this code understands must be refused, not silently mis-read. ``engine``
            # turns this into a disabled coach with a clear "re-bake / upgrade" path.
            if version != MANIFEST_VERSION:
                raise ManifestError(
                    f"manifest version {version} is not supported by schema {MANIFEST_VERSION} "
                    "— upgrade the sidecar or re-bake the bank"
                )
            raw_clips = d["clips"]
            if not isinstance(raw_clips, dict):
                raise ManifestError("manifest 'clips' is not an object")
            clips = {str(cid): ClipEntry.from_dict(e) for cid, e in raw_clips.items()}
            return Manifest(
                version=version,
                samplerate=int(d["samplerate"]),
                voice_signature=str(d["voice_signature"]),
                vocabulary_hash=str(d["vocabulary_hash"]),
                clips=clips,
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ManifestError(f"malformed manifest: {exc}") from exc

    @staticmethod
    def load(path: str | Path) -> Manifest:
        """Load a manifest JSON file. Raises :class:`ManifestError` on parse/structure failure."""
        p = Path(path)
        try:
            text = p.read_text(encoding="utf-8")
        except OSError as exc:
            raise ManifestError(f"cannot read manifest {p}: {exc}") from exc
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ManifestError(f"invalid manifest JSON {p}: {exc}") from exc
        return Manifest.from_dict(data)

    # ---- validation --------------------------------------------------------------------------

    def validate(self, bank_dir: str | Path | None = None) -> ValidationReport:
        """Check the manifest against the current vocabulary and (optionally) the on-disk clips.

        * ``vocabulary_matches`` is ``False`` when the baked ``vocabulary_hash`` differs from the
          current :func:`vocabulary.vocabulary_hash` — i.e. the wording changed but the bank was not
          re-baked. When this is false the engine MUST NOT play any clip (it could be stale).
        * ``problems`` lists missing clip files and sha256 mismatches when ``bank_dir`` is supplied.

        Never raises on content problems — it *reports* them so the caller can degrade per clip.
        """
        problems: list[str] = []
        vocab_ok = self.vocabulary_hash == vocab.vocabulary_hash()
        if not vocab_ok:
            problems.append(
                "vocabulary_hash mismatch: bank was rendered against different wording "
                f"(bank={self.vocabulary_hash[:12]}…, current={vocab.vocabulary_hash()[:12]}…) "
                "— re-bake the phrase bank"
            )
        if bank_dir is not None:
            base = Path(bank_dir)
            for entry in sorted(self.clips.values(), key=lambda e: e.clip_id):
                fp = base / entry.file
                if not fp.is_file():
                    problems.append(f"{entry.clip_id}: missing clip file {entry.file}")
                    continue
                digest = _sha256_file(fp)
                if digest != entry.sha256:
                    problems.append(
                        f"{entry.clip_id}: sha256 mismatch (file={digest[:12]}…, "
                        f"manifest={entry.sha256[:12]}…)"
                    )
        return ValidationReport(vocabulary_matches=vocab_ok, problems=problems)


def _sha256_file(path: str | Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def sha256_bytes(data: bytes) -> str:
    """sha256 hex of an in-memory byte string (used by the bake step for per-clip hashing)."""
    return hashlib.sha256(data).hexdigest()
