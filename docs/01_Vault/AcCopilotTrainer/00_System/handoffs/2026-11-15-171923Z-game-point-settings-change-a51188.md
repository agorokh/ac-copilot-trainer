---
type: handoff
status: active
created: 2026-11-15
updated: 2026-11-15
issue: https://github.com/agorokh/ac-copilot-trainer/issues/988
relates_to:
  - AcCopilotTrainer/00_System/handoffs/2026-11-15-160200Z-game-point-open-start-a51188.md
  - AcCopilotTrainer/00_System/handoffs/2026-11-14-221000Z-game-point-rebuild-47ddb3ec-a51188.md
  - AcCopilotTrainer/00_System/glossary/install-paths.md
---

# Rig: what changed in Game Point settings.json on 2026-11-14 at 22:34Z

**Resume pointer.** On the operator's instruction "Find out what changed in settings.json on the
rig", the current file was compared with a backup of the earlier one. This answers the last "Not
verified" line of the first `relates_to` node (who changed it, which keys). The check was
read-only: the settings file and the backup are untouched.

## The change

Both files were written at 22:34:42Z on 2026-11-14. Two of 16 keys differ.

| Key | Before | After |
|---|---|---|
| `resilient_track` | `magione` | `spa` |
| `ac_user_dir` | empty (auto-detect) | `C:\Users\arsen\OneDrive\Documents\Assetto Corsa` |

- Before: SHA-256 `ffb1c4bb850fb2cfea4bee99b9b8b1f789c540d6a1f88218228506ae97b1a65b`, 492 bytes.
  This is the hash in the rebuild node, so the comparison is against that exact file.
- After: SHA-256 `38bd2180060be06a49782bd440650fd0f7dca32e7e7e28269fb4c39866af3578`, 540 bytes.
- Unchanged, among others: `resilient_car` (`ks_porsche_911_gt3_r_2016`), `resilient_layout`
  (empty), `start_simhub` (true), `sidecar_port` (8765), `voice_bank` (empty), `voice_tts` (false).

## Who wrote it

A `rig-operator` skill installed in Codex on the rig, at `%USERPROFILE%\.codex\skills\rig-operator\`
(created 22:45Z by file time, scripts last edited 23:40Z). Its `scripts\rig.py` has a
`prepare_launcher` step that sets exactly `resilient_car`, `resilient_track`, `resilient_layout`
and `ac_user_dir` to the values above. It refuses to run while Game Point is open and backs up
the old file first. The backup is in the Game Point user directory under
`rig-operator\backups\`, named `GamePoint-settings.json-<old sha256>.bak`.

## Effect

Both keys are read only by the resilient ("Stable AC") launch path in
`tools/rig_launcher/supervisor.py`. `resilient_track` is passed to that launch as `--track`.
`ac_user_dir` is where that path looks for CSP's `cfg\extension\gui.ini`; when empty, the
launcher chooses between `Documents\Assetto Corsa` and `OneDrive\Documents\Assetto Corsa`
itself. A normal START does not read either key.

## Not verified

- The Codex session log entry for the run that wrote the file was not found. Attribution rests
  on the script's code and the backup's location and name.
- The same backups folder holds earlier copies of three other files, written between 22:34Z and
  23:29Z: Content Manager's `Values.data` (2 copies), MOZA Pit House `settings.ini` (3 copies)
  and MOZA Racing Lab `config.json` (3 copies). Those were not compared with the current files.
- Whether the Spa selection is still wanted for the resilient launch was not asked.
