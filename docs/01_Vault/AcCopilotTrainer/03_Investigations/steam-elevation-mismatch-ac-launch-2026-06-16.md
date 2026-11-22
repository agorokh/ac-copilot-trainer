---
type: investigation
status: active
memory_tier: canonical
created: 2026-06-16
updated: 2026-06-16
relates_to:
  - AcCopilotTrainer/00_System/glossary/rig-network.md
  - AcCopilotTrainer/00_System/glossary/install-paths.md
  - AcCopilotTrainer/03_Investigations/issue-188-wrap-skew-rig-verification.md
---

# Rig gotcha — "Steam API has failed to initialize" = Steam/launcher elevation mismatch

## Symptom

On `AG_PC`, launching AC (direct `acs.exe` **or** via Content Manager → Drive) fails with a modal:

> **Failed to launch the race — Can't launch Assetto Corsa: Steam API has failed to initialize.**

…even though the Steam client window shows fully logged in and online (store renders, persona
`ag0816`). The AC process window title flips to `Failed to launch the race`; shared-memory stays
`status=OFF`, packets `0`.

## Root cause (verified 2026-06-16)

**Integrity-level (elevation) mismatch between the Steam client and the game launcher.**

- `steam.exe` was running **elevated** (admin); **Content Manager** runs **non-elevated**.
- `HKCU\Software\Valve\Steam\ActiveProcess` showed **`pid=0`, `ActiveUser=0`** — i.e. no Steam
  client API session was registered for games to bind to, despite the UI being logged in.
- A non-elevated game process cannot bind the elevated Steam client's API → init fails.

Note: `ag0816` is just the **PersonaName**; `loginusers.vdf` `AccountName=agorokh3` owns AC
(`appmanifest_244210.acf` `LastOwner` matches). So it is **not** a wrong-account problem — don't
chase that.

## Fix (no credentials needed)

1. `& "C:\Program Files (x86)\Steam\steam.exe" -shutdown` and wait for all `steam*` procs to exit.
2. Relaunch Steam **non-elevated** so it matches Content Manager. From an elevated agent shell, use
   the de-elevation trick: `Start-Process "C:\Windows\explorer.exe" -ArgumentList "<steam.exe>"`
   (explorer runs at medium integrity → child Steam is non-elevated).
3. Auto-login restores the session with **no password/2FA** (`RememberPassword=1`,
   `AllowAutoLogin=1`, device already Steam-Guard-trusted). If a credential/2FA prompt appears,
   that is operator-gated → stop and surface.
4. Content Manager → Drive → **Go!** then launches straight onto the track (immediate-start menu
   skip works once Steam is healthy).

## Detection one-liners

```powershell
# 0/0 here while "logged in" == the wedge:
Get-ItemProperty 'HKCU:\Software\Valve\Steam\ActiveProcess' | Select pid,ActiveUser
# elevation of a pid (TokenElevation): non-zero == elevated
```

The autonomous agent shell on the rig itself runs **elevated** — so never launch `acs.exe`
directly from it (that yields an elevated game vs non-elevated Steam → same failure). Always launch
the game through the non-elevated Content Manager.
