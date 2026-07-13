"""Tablet GT dashboard package (issue #531 Part A).

The self-contained dashboard page lives in ``web/tablet_dash.html`` and is served by the
sidecar at ``/tablet/dash`` (same port as the WebSocket; USB ``adb reverse tcp:8765``
deployment). Fonts under ``web/fonts/`` are vendored copies of the Racing Atelier faces
already shipped in ``src/ac_copilot_trainer/content/fonts/`` — duplicated here so the
sidecar serves the kiosk fully offline without reaching outside its own package tree.
"""
