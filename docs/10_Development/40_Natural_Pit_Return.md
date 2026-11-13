# Natural pit return in the canonical harness

Issue #956's adopted autonomous protocol requires the archived stint and current
pit interaction to share their native trainer session. Teleporting to pits starts
a disjoint trainer stint by design. Keep that reset and all prescription guards.

`tools.ac_harness.auto_drive --natural-pit-return` instead retains the existing
external controller after the observed lap window and archive-finalization grace.
It follows the authored `fast_lane.ai` forward to `pit_lane.ai`, then smoothly
offsets into the actual assigned `ac.getCar(0).pitTransform`. The existing config
bridge exposes that transform as read-only `harnessPitBox`, with offline,
session and combo metadata. It is navigation data, never setup-write permission.
The parent event loop reads it through a distinct read-only connection before
starting the driving thread and confirms it again after native arrival while
retaining the braked controller. The driving loop performs no network reads.

The opt-in requires `--laps N`, `--driver ggv` or `racing`, `--no-spawn-line`,
`--max-recoveries 0`, `--sim-death-retries 0` and `--setup-verify-retries 0`.
Ordinary drives retain their current behavior. Existing lease ownership, process
takeover, packet-stagnation, abort and controller-cleanup guards still apply.

The return phase has a 240-second cap, a 60 km/h speed target ceiling, an
8-meter route-deviation bound, and a 12-second progress bound. Overlong
geometry is rejected before navigation: a route longer than 3.5 km
cannot fit the speed/deadline envelope with 30 seconds reserved for approach.
This is a bounded return capability for #956's Magione campaign. Its authored
return route is about 2.23 km; that geometry check provides no native arrival
credit. General long-track return is outside this change's supported envelope.
For example, a post-lap forward wrap on Spa can exceed 3.5 km and is deliberately
denied before navigation. The 240-second cap is not enlarged to admit it.
Missing or disconnected authored geometry, incompatible box heading/elevation, missing
native state or any failed observer pipeline stops the attempt. No teleport,
recovery, setup mutation or handoff to AC's built-in AI occurs in this phase.

Geometric proximity only commands braking. Arrival requires three separated,
dual-advancing LIVE graphics/physics samples reporting actual `is_in_pit`,
speed at most 0.1 km/h, position within 1.5 m of the assigned box, no native lap
rollback, and unchanged native session/combo/pit geometry read back afterward.
The report records `drive.pit_return_status` and native proof metadata. Any
requested return without verified arrival vetoes a successful drive report.
The existing outer rig owner must retain its lease until return and teardown
settle. Native setup admission and independent prescription audit/readback remain
separate required checks after controller release.

A natural pit in-lap may cross start/finish. Its raw archive remains immutable
evidence; it does not replace the predeclared flying-lap window. Acceptance must
retain all attempted captures, freeze any such handling before collection, and
still prove the actual session, lap window, setup and source hashes. Software
and geometry tests grant no real-case or live-safety credit. Keep the normal
experiment disabled and #956 open until its adopted acceptance passes.
