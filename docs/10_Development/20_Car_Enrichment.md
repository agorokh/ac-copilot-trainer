# Car enrichment registry and SimHub bridge

Issue [#534](https://github.com/agorokh/ac-copilot-trainer/issues/534) establishes
the Python sidecar as the single authority for car-class enrichment. The
trainer publishes only `car_id`; the sidecar resolves and enriches the existing
`session` snapshot; direct WebSocket clients and SimHub consume the same value.

## Resolver contract

Resolution is deterministic and ordered:

1. Exact, case-insensitive entry in
   `tools/ai_sidecar/car_class_overrides.yml`.
2. Normalized `ui_car.json` `class`, `tags`, and `specs` metadata.
3. Conservative `road` fallback when metadata is absent, malformed, or unknown.

The stable vocabulary is:

`rear-engine-gt`, `front-engine-gt`, `mid-engine-gt`, `formula`, `prototype`,
`hypercar`, `touring`, `drift`, `gt`, `race`, and `road`.

Engine placement is never guessed from drive layout, power, or mass. AC's GT
metadata does not encode it reliably, so those facts belong in the override
registry. The registry is JSON-compatible YAML so the sidecar and frozen
launcher remain stdlib-only; malformed versioned data fails explicitly in
tests. Unsafe car IDs cannot escape `content/cars`.

The sidecar resolves once per `session` identity event, not on high-rate
telemetry. It publishes class, provenance, registry version, and the original
raw UI class. No derived class is written into a setup, journal, or user
settings.

## SimHub bridge

`tools/simhub_car_enrichment` contains a .NET Framework 4.8 plugin built against
SimHub's supported PluginSdk. It exposes:

- `[AcCopilotDataPlugin.CarClass]`
- `[AcCopilotDataPlugin.CarId]`
- `[AcCopilotDataPlugin.ClassSource]`
- `[AcCopilotDataPlugin.RegistryVersion]`
- `[AcCopilotDataPlugin.SidecarConnected]`
- `[AcCopilotDataPlugin.TrainerConnected]`

The plugin does no work on SimHub's `DataUpdate` critical path. A background
WebSocket subscribes to `connection` and `session`, reconnects with bounded
backoff, and inherits `AC_COPILOT_SIDECAR_PORT` plus the optional secret token.
If the trainer heartbeat stops, the public class fails closed to `unknown`
within 3.5 seconds even when the sidecar socket remains open.

SimHub's supported profile selector matches games/cars, not arbitrary custom
properties. Use the property inside one operator-curated dashboard or ShakeIt
formula:

```text
if([AcCopilotDataPlugin.CarClass] = 'rear-engine-gt', 1.15, 1.0)
```

The project does not install the DLL, enable the plugin, rewrite
`ShakeITBassShakersSettingsV2.json`, or alter any operator-created profile.
That preserves the launcher rule that SimHub is an optional peer and prevents
split ownership of profile state. Build and manual install instructions are in
`tools/simhub_car_enrichment/README.md`.

The tablet dashboard remains on its direct sidecar WebSocket. Its real
per-car spinner ranges and `rpm_max` behavior from #531 are not duplicated in
SimHub.

## Hardware and audio disposition

| Part | Status | Decision |
| --- | --- | --- |
| C — wind | Hardware-gated | #117 remains the Arduino/fan prerequisite. `CarClass` is now ready for a future class curve, but this repository does not actuate a fan that is not built. |
| D — pedal haptics | Dormant/operator-gated | #119 was dropped. The rig now has a SimHub profile naming a TT25 pedal, so the old “empty bracket” premise is stale. No automatic class effect is enabled until the operator decides whether the live TT25 supersedes the dropped Arduino design and confirms channel/thermal safety. |
| E — rear-engine drama | Investigated/no default mutation | Keep AC/FMOD 5.1 audio untouched. If more emphasis is desired, first bench a low-gain, seat-only class-gated ShakeIt effect. Per-car sound mods are manually maintained content; Voicemeeter adds another persistent routing authority. Neither is the default enrichment path. |

The recommended rear-engine experiment is seat-only specifically because the
live profile names a pedal TT25. It must not reuse or amplify the pedal channel
without an explicit hardware and thermal review.

## Verification and rollback

Run:

```powershell
python -m tools.ai_sidecar.car_class --ac-root 'C:\Program Files (x86)\Steam\steamapps\common\assettocorsa'
$env:SIMHUB_INSTALL_PATH = 'C:\Program Files (x86)\SimHub'
& 'C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools\MSBuild\Current\Bin\MSBuild.exe' `
  .\tools\simhub_car_enrichment\AcCopilot.CarEnrichment\AcCopilot.CarEnrichment.csproj `
  /restore /p:Configuration=Release
```

After an operator installs/enables the DLL, verify rear-engine GT,
front-engine GT, and trainer-disconnected `unknown` in SimHub's property
picker or NCalc preview. Do not infer success from a DLL build alone.

Rollback is additive: disable/remove `AcCopilot.CarEnrichment.dll` while SimHub
is stopped. The sidecar will continue publishing the enriched `session` frame
to direct clients, and no SimHub profile needs restoration because this
delivery never edits one.
