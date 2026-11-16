---
type: investigation
status: active
memory_tier: canonical
created: 2026-11-16
updated: 2026-11-16
issue: https://github.com/agorokh/ac-copilot-trainer/issues/1006
relates_to:
  - AcCopilotTrainer/10_Rig/haptics-thermal-failure-2026-04-18.md
  - AcCopilotTrainer/00_System/glossary/install-paths.md
---

# SimHub ShakeIt: changing shaker gain at runtime without editing settings

Question (#1006 Part 1 decision gate): which mechanism changes the ShakeIt Bass Shakers overall
gain while SimHub runs, without editing `ShakeITBassShakersSettingsV2.json`?

## Evidence

Read-only .NET reflection over `C:\Program Files (x86)\SimHub\SimHub.Plugins.dll` on the rig PC
(`AG_PC`), 2026-11-16, SimHub not running. String literals and call targets were read from the
IL of the named methods.

- Plugin type: `SimHub.Plugins.DataPlugins.ShakeItV3.ShakeITBSV3Plugin`, base
  `ShakeITV3PluginBase<,>`. (`ShakeITMotorsV3Plugin` is the motors sibling.)
- `ShakeITV3PluginBase.ConfigureControls` calls `PluginManager.AddAction(name, GetType(), ...)`
  for `MainFeedbackLevelIncrement`, `MainFeedbackLevelDecrement`, `ToggleMuteFeedback` and
  `ResetCalibration`, and stores them in `Settings.Actions` as
  `GetType().Name + ".MainFeedbackLevelIncrement"` and so on. Full action names:
  `ShakeITBSV3Plugin.MainFeedbackLevelIncrement`, `ShakeITBSV3Plugin.MainFeedbackLevelDecrement`,
  `ShakeITBSV3Plugin.ToggleMuteFeedback`.
- `ShakeITV3PluginBase.Init` attaches properties `GlobalGain` and `IsMuted` under the plugin type,
  so `ShakeITBSV3Plugin.GlobalGain` and `ShakeITBSV3Plugin.IsMuted`.
- `PluginManager` offers `TriggerAction(string)`, `TriggerAction(string, bool preventEvents)` and
  `GetPropertyValue(string)` to plugins.
- The SimHub folder grants `BUILTIN\Users` FullControl, and MSBuild 2022 Build Tools are installed,
  so the repo's SimHub plugin can be built and installed on the rig without elevation.

## Conclusion

Candidate 1 of #1006 works: a plugin of ours triggers the same actions SimHub's *Controls and
events* mapping uses and reads `GlobalGain` / `IsMuted` back. No settings file is touched, and
SimHub keeps owning the shaker endpoint volume (`ControlVolume: true`).

## Not verified

- That `TriggerAction` from a plugin's background thread behaves like a mapped input.
- The `GlobalGain` change per action (expected `GainChangeStep`, currently 1).
- That the property names resolve at runtime as derived above.

All three are checked by readback the first time the plugin runs in SimHub.
