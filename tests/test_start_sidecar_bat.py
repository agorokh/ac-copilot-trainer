from __future__ import annotations

from pathlib import Path


def test_start_sidecar_bat_supports_rig_screen_env_contract() -> None:
    script = Path("src/ac_copilot_trainer/start_sidecar.bat").read_text(encoding="utf-8")
    normalized = " ".join(line.strip() for line in script.splitlines())

    assert "AC_COPILOT_SIDECAR_TOKEN" in script
    assert "AC_COPILOT_SIDECAR_EXTERNAL_BIND" in script
    assert "AC_COPILOT_SIDECAR_PORT" in script
    assert 'if "!AC_COPILOT_SIDECAR_PORT!"==""' in normalized
    assert 'set "AC_COPILOT_SIDECAR_PORT=8765"' in normalized
    assert 'if not "!AC_COPILOT_SIDECAR_TOKEN!"=="" (' in normalized
    assert 'if "!AC_COPILOT_SIDECAR_EXTERNAL_BIND!"==""' in normalized
    assert 'set "AC_COPILOT_SIDECAR_EXTERNAL_BIND=0.0.0.0"' in normalized
    assert "--external-bind !AC_COPILOT_SIDECAR_EXTERNAL_BIND!" in script
    assert "--host 127.0.0.1" in script
    assert "--token" not in script
    assert "py -3 -m tools.ai_sidecar !SIDECAR_ARGS!" in script
    assert "python -m tools.ai_sidecar !SIDECAR_ARGS!" in script
