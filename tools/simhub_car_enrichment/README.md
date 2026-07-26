# SimHub car-enrichment bridge

This supported SimHub SDK plugin subscribes to the sidecar's authoritative
`session` and `connection` snapshots and exposes:

- `[AcCopilotDataPlugin.CarClass]`
- `[AcCopilotDataPlugin.CarId]`
- `[AcCopilotDataPlugin.ClassSource]`
- `[AcCopilotDataPlugin.RegistryVersion]`
- `[AcCopilotDataPlugin.SidecarConnected]`
- `[AcCopilotDataPlugin.TrainerConnected]`

Build from a Visual Studio Developer PowerShell:

```powershell
$env:SIMHUB_INSTALL_PATH = 'C:\Program Files (x86)\SimHub'
msbuild .\tools\simhub_car_enrichment\AcCopilot.CarEnrichment\AcCopilot.CarEnrichment.csproj `
  /restore /p:Configuration=Release
```

After stopping SimHub, copy `AcCopilot.CarEnrichment.dll` from `bin\Release`
into the SimHub install directory, then restart SimHub and enable the plugin.
The repository never copies it automatically or edits an operator-created
SimHub/ShakeIt profile.

Use the property from one curated ShakeIt profile or dashboard formula, for
example:

```text
if([AcCopilotDataPlugin.CarClass] = 'rear-engine-gt', 1.15, 1.0)
```

The bridge reads `AC_COPILOT_SIDECAR_PORT` and the optional
`AC_COPILOT_SIDECAR_TOKEN` from the inherited environment. It reconnects with
a bounded backoff. `CarClass` fails closed to `unknown` within 3.5 seconds when
the trainer's one-second `connection` heartbeat stops, even if the sidecar
process remains connected.
