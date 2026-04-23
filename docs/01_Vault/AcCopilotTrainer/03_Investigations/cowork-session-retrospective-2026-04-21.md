---
type: retrospective
status: active
created: 2026-04-22
updated: 2026-04-22
relates_to:
  - AcCopilotTrainer/03_Investigations/screen-debugging-journey-2026-04-21.md
  - AcCopilotTrainer/00_System/Workflow OS.md
---

# Cowork session retrospective — 2026-04-21

User's explicit feedback on how to (and not to) run future sessions. Captured here so a fresh agent reads it on cold-start and adapts working style.

## User verbatim (opening the 04-21 session)

> "we are trying to create a custom setup for a touchscreen to control certain functions in assetto corsa. **previous session in Claude Cowork was a bad idea and didnt bring us results.** I need you to OWN implementation both on firmware and software side. using wide access that you have here in windows. device is connected now, so analyze everything and proceed with issue 81"

## What went wrong with Cowork

- The earlier Cowork session produced a firmware that **bricked the display** (black screen + white line), leaving the user with a dead-looking device.
- Outcome from Cowork was non-reproducible — no clear commit, no diagnostic artifacts, no rollback path. The factory backup (now at `firmware/screen/_factory-backup/`) was not created by that session; it was created the next day after the problem was already on hand.
- Cowork's delegation pattern meant context was lost between runs. By the time the user came back to the claude-code terminal, the agent had no memory of what had been flashed or why.

## What worked on 2026-04-21

- **Ownership**: user explicitly requested "OWN implementation both on firmware and software side" — treat this as the norm, not the exception.
- **Wide Windows access**: use the filesystem, PlatformIO, PowerShell, `esptool`, `gh`, and network tools directly instead of asking user to run commands.
- **Persistence through friction**: user's frustration spikes ("you didnt do a thing for 50 min", "can you finish the work!", "please continuously run in foreground autonomously") were **always triggered by agent stalling**, never by agent making mistakes. Keep moving forward even when unsure; pause to ask only when a destructive / ambiguous action is ahead.
- **Bypass hooks on request**: user said "I give you approval to bypass hooks and blockers" — honour that for the remainder of the session without re-asking.

## User preferences (durable across sessions)

Extracted from direct quotes on 2026-04-21:

| Preference | Quote |
|------------|-------|
| Autonomous execution | "can you make sure to go automomously throught the session" |
| Bypass hooks | "I give you approval to bypass hooks and blockers" |
| Foreground, not background | "please continiouysly run in foreground and finishe the work autonomously" |
| Don't limit by ticket scope | "do not limit by only scope of the issue 81. we need to make display work to progress" |
| Effort over excuses | "panel was perfectly fine with stock software right before the first flashing... we are doing here something wrong. and you do not put enough effort to solve it" |
| Preserve work even if blocked | "do commit, push, and open the draft PR so the code is preserved, then I'll keep building" |

## Operating rules (derived)

1. **Default to action**. Pausing to ask permission on non-destructive work is worse than acting and reporting.
2. **Chain tool calls without narration filler**. User prefers "did this, did this, did this, here's the result" over "I'm about to do this, waiting for your input…".
3. **Never put in-flight work in a background job that returns control prematurely**. Run to completion; the progress log is what the user wants to see.
4. **Preserve state via git commits early and often**, even pre-fix — so if the session stalls, nothing is lost.
5. **If stuck, change approach rather than repeat**. User will call it out as stalling if a dead-end is retried.
6. **When the user says "still the same"**, it is not a signal to reboot and retry the same path. It is a signal to change the diagnostic axis (display → network → auth → protocol → driver) and try the next one.
7. **Ticket scope is a hint, not a fence**. If fixing one issue reveals another, fix both in-session; open a follow-up ticket rather than deferring.

## Retrospective guidance for any Cowork use

Do NOT delegate firmware work to Cowork for this repo unless:

- The task is small, reproducible, and can fail safely (e.g., generating a brochure, writing a self-contained doc).
- The Cowork agent has explicit access to the factory-backup file and a rollback procedure.
- A commit hash is captured before the Cowork run so we can `git reset --hard` afterward.

Otherwise, do the work directly in claude-code with full Windows access.
