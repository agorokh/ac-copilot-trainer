# MOZA data qualification

Issue [#815](https://github.com/agorokh/ac-copilot-trainer/issues/815) separates
research, normalization, reporting and live activation. Part A is complete.
Part B implements native control provenance first, then the local cache reader.
This document is the implementation contract; CLI examples and validation will
be completed with the Part B implementation.

## Native recordings and control authority

The trainer can record a MOZA-assisted lap as `source=in_game`, including a PB
flag. Those fields describe collection and timing, not who controlled the car.
The raw archive remains immutable. An explicit attribution record binds control
evidence to its original byte hash, canonical payload hash and session/lap
identity. It must also apply when a consumer receives the parsed dictionary or
a copy of the same archive.

One attribution ledger is selected through `AC_COPILOT_LAP_ATTRIBUTIONS`, with
the canonical AC Documents app journal as the default. Consumer checks resolve
that ledger at archive boundaries. Invalid, duplicate or mismatched attribution
cannot fall back to an unattributed lap or be overridden by permissive embedded
metadata. Tests and offline qualification use an isolated ledger.

AI, shared and unknown control are distinct from human control. Managed records
with those authorities cannot count toward human PB/progression or plant fitting.
Unrelated historical archives retain their existing behavior and are explicitly
unattributed; this change does not certify them as human or rewrite their bytes.

## Shared consumer checks

One shared policy evaluates the intended use, identity, channel semantics,
validity and coverage. Archive-facing reference, Coach/observer, MAP, report,
profile and plant boundaries retain their stricter existing checks. A requested
use is not permission to bypass missing evidence. Track Titan behavior and the
existing advisory/voice pipeline remain in place.

## MOZA caches

Only explicitly selected local files are read. The reader checks stable bytes
and records hashes and source versions. Processed/chart data stays distinguishable
from measured native telemetry. Unsupported steering conversion, elapsed origin
or coordinates stay unavailable. The importer does not fabricate missing channels,
inherit the reference builder's default valid/PB flags, or label MOZA as MoTeC.

Parsing an inspection artifact is separate from qualifying it as a reference.
Zero eligible evaluated laps cannot supply coaching advice even when scores exist.
No live reference, voice activation, rig launch or controller action follows from
Part B. Those decisions remain in later Parts of #815.
