@echo off
REM ac-copilot-trainer Python sidecar launcher (issue #77 part A)
REM Auto-spawned by ws_bridge.lua via os.runConsoleProcess at app load.
REM
REM Hardcoded REPO_ROOT below: cleanest option for solo-developer Windows-only
REM setup. To redeploy on a different machine, change this one line.

SET REPO_ROOT=C:\Users\arsen\Projects\ac-copilot-trainer

REM Ollama coaching env (matches the values that were verified in PR #75).
SET AC_COPILOT_OLLAMA_ENABLE=1
SET AC_COPILOT_OLLAMA_HOST=http://127.0.0.1:11434
SET AC_COPILOT_OLLAMA_MODEL=llama3.2:3b
SET AC_COPILOT_OLLAMA_TEMPERATURE=0.35
SET AC_COPILOT_OLLAMA_NUM_PREDICT=160
SET AC_COPILOT_OLLAMA_TIMEOUT_SEC=60
SET AC_COPILOT_OLLAMA_DEBRIEF_TIMEOUT_SEC=60

cd /d "%REPO_ROOT%"
IF NOT EXIST "%REPO_ROOT%\tools\ai_sidecar" (
    echo [start_sidecar] ERROR: tools\ai_sidecar not found at %REPO_ROOT%
    echo [start_sidecar] Edit REPO_ROOT in this .bat to point at your repo checkout.
    exit /b 2
)

REM Try py launcher first (handles multiple Python installs); fall back to plain python.
where py >nul 2>nul
IF %ERRORLEVEL%==0 (
    py -3 -m tools.ai_sidecar --host 127.0.0.1 --port 8765
) ELSE (
    python -m tools.ai_sidecar --host 127.0.0.1 --port 8765
)
