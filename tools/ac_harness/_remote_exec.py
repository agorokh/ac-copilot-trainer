"""Console-session entry point for :mod:`tools.ac_harness.remote_launcher` (#697).

Task Scheduler's ``/tr`` used to point at a generated ``run.cmd`` inside the shared, agent-writable
``.scratch`` tree. That made the scheduled payload a **peer-writable script**: any agent on the rig
could replace it between ``/create`` and first execution and have Task Scheduler run an arbitrary
command in the console session as the logged-on user. Executing a file we already treat as untrusted
was the defect; relocating it would not have fixed it.

``/tr`` now points at the repo's own interpreter running *this* file — version-controlled code, the
same trust boundary the harness already runs under — which reads a control file, re-validates every
argv token, and spawns the payload **without a shell**.

Run as a script rather than ``-m`` because ``schtasks`` has no working-directory option, so the repo
root is derived from this file's location and put on ``sys.path`` before the package import.
"""

from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from tools.ac_harness.remote_launcher import (  # noqa: E402
    EXEC_FAILURE_RC,
    RemoteLaunchError,
    execute_control_file,
)

if __name__ == "__main__":
    # Exit with the SAME code the sentinel records. Task Scheduler surfaces this as `Last Result`,
    # and the deletion verdict now requires the two to agree — a binding that only holds if a
    # failure exits EXEC_FAILURE_RC rather than letting the traceback pick an unrelated code.
    try:
        raise SystemExit(execute_control_file(sys.argv[1] if len(sys.argv) > 1 else ""))
    except RemoteLaunchError as exc:
        print(f"remote-exec: {exc}", file=sys.stderr)
        raise SystemExit(EXEC_FAILURE_RC) from exc
