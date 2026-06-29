from __future__ import annotations

import re
from pathlib import Path


def test_start_sidecar_bat_supports_rig_screen_env_contract() -> None:
    script = Path("src/ac_copilot_trainer/start_sidecar.bat").read_text(encoding="utf-8")

    assert "AC_COPILOT_SIDECAR_TOKEN" in script
    assert "AC_COPILOT_SIDECAR_EXTERNAL_BIND" in script
    assert "AC_COPILOT_SIDECAR_PORT" in script
    assert re.search(
        r'^\s*if\s+"!AC_COPILOT_SIDECAR_PORT!"==""\s+'
        r'set\s+"AC_COPILOT_SIDECAR_PORT=8765"\s*$',
        script,
        flags=re.IGNORECASE | re.MULTILINE,
    )
    assert 'if not "!AC_COPILOT_SIDECAR_TOKEN!"=="" (' in script
    assert re.search(
        r'^\s*if\s+"!AC_COPILOT_SIDECAR_EXTERNAL_BIND!"==""\s+'
        r'set\s+"AC_COPILOT_SIDECAR_EXTERNAL_BIND=0\.0\.0\.0"\s*$',
        script,
        flags=re.IGNORECASE | re.MULTILINE,
    )
    assert "--external-bind !AC_COPILOT_SIDECAR_EXTERNAL_BIND!" in script
    assert "--host 127.0.0.1" in script
    assert "--token" not in script
    assert "py -3 -m tools.ai_sidecar !SIDECAR_ARGS!" in script
    assert "python -m tools.ai_sidecar !SIDECAR_ARGS!" in script
