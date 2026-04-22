---
type: artifact
status: active
created: 2026-04-18
updated: 2026-04-18
relates_to:
  - 10_Rig/_index.md
  - 10_Rig/dual-transducer-brake-body-v1.md
tags: [3d-print, moza-srp, bracket, toybox, parametric]
---

# SRP brake pedal transducer bracket — v1.1

Parametric bolt-on bracket that mounts the AliExpress 4 Ω 25 W tactile transducer (**one unit**; no spare on hand) to the MOZA SRP (load-cell) brake pedal chassis. Printable on the Toybox 3D printer (75 × 80 × 90 mm build envelope, PLA, 200 µm layers).

## Artifact location

Outside the vault, in the Cowork working folder:

```
AC Copilot/3d-models/srp-brake-transducer-bracket-v1/
    srp_brake_transducer_bracket.scad   # OpenSCAD source (preferred for edits)
    generate_stl.py                     # Python/trimesh regeneration (if OpenSCAD unavailable)
    srp_brake_transducer_bracket.stl    # pre-rendered STL (default parameters)
    README.md                           # calipers checklist, print + assembly notes
```

## Architecture (v1.1, post-Toybox-flatness rework)

Single flat rectangular plate — no cup walls, no cantilever arm. The transducer flange bolts onto the top face of the plate; the body hangs through a central bore into free air on the opposite face. A shallow 3 mm flange recess on the top face locates the flange so it cannot slip while you tighten the bolts.

Print orientation is plate-flat on the bed (≈ 5600 mm² of bed contact, zero overhangs, no supports). After print, the bracket is rotated 90° for installation: the bottom face presses against the outer face of the SRP brake pedal's side rail, and the transducer ends up horizontal, piston axis perpendicular to the rail — so vibration couples directly into the pedal frame rather than into the rig floor.

## Verified envelope (default parameters)

| Axis | Size | Toybox limit | Status |
|------|------|--------------|--------|
| X | 72.0 mm | 75 mm | **OK** |
| Y | 78.0 mm | 80 mm | **OK** |
| Z |  5.0 mm | 90 mm | **OK** |

Bed-contact area: plate is 72 × 78 mm solid rectangle minus the 60 mm bore and four small bolt holes. Contact roughly 5600 mm². Volume 10 573 mm³, PLA mass at 1.24 g/cc ≈ 13 g. Envelope check runs automatically on both the SCAD render and the Python generator (assertions fail the build if any dimension exceeds Toybox).

## SRP bolt pattern — why slotted

MOZA does not publish a dimensioned SRP chassis drawing, and the vendor support site was blocked from the sandbox's egress proxy at design time. Rather than guess a single "correct" hole spacing, the plate uses **elongated slots** along X with ± 8 mm of travel from the nominal centre-to-centre. Any SRP hole spacing within srp_mount_spacing ± slot_travel bolts up without re-printing. Nominal defaults: 40 mm centre-to-centre, M6 clearance (6.6 mm bore + 12 mm washer relief on the pedal-seating face). Edit and re-render for M5 / M4 hardware or different spacings.

## Calibrated measurements still needed

| Variable | What to measure | Default | Why it matters |
|----------|-----------------|---------|----------------|
| transducer_od | Transducer body OD (calipers) | 58 mm | Bore size through the plate |
| transducer_lip_od | Mounting flange OD | 64 mm | Flange-locating recess diameter |
| transducer_bolt_pcd | Flange bolt pitch circle | 50 mm | Flange bolt hole positions |
| transducer_bolt_n | Flange bolt count (3 or 4) | 4 | Number of PCD holes |
| transducer_bolt_d | Flange bolt clearance | 3.4 mm (M3) | Set 4.4 mm for M4 |
| srp_mount_spacing | SRP tapped-hole spacing | 40 mm | Centre of the slot pair |
| srp_bolt_d | SRP bolt clearance | 6.6 mm (M6) | Set 5.6 (M5) / 4.5 (M4) as needed |

Each is a one-variable edit in the SCAD (or Python) source. The README has the full checklist.

## Wiring

Transducer wire → amp **Left** channel. Amp is the 200 W Douk stereo class-D unit (Amazon ASIN B0C7C7GD9R), fed from the PCM2902 USB DAC. Right channel continues to drive the Douk BS-1 body shaker under the bucket seat. See dual-transducer-brake-body-v1.md for the full signal chain.

## Next-revision candidates

- Mirror-image bracket for the throttle pedal (Phase 2) — blocked on purchase of a second matching 4 Ω 25 W transducer.
- Heat-set threaded inserts in the PCD flange holes if PLA threads strip after a few remove/reinstall cycles.
- PETG variant for hot-garage (> 35 °C ambient or direct sun) environments.

## Change log

- 2026-04-18 — v1 created. L-bracket with cup + cantilever, 72 × 72 × 55 mm, 2466 triangles. Problem discovered at review: only ~260 mm² bed contact, cup overhanging plate in Y. Not reliably printable on Toybox.
- 2026-04-18 — v1.1 rework. Single flat plate, central bore + flange recess + slotted SRP bolts. 72 × 78 × 5 mm, 2360 triangles, ~13 g PLA, ~5600 mm² bed contact, zero overhangs.