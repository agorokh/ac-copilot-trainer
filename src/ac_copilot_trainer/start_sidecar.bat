@echo off
REM ac-copilot-trainer Python sidecar launcher (issue #77 part A)
REM Auto-spawned by ws_bridge.lua via os.runConsoleProcess at app load.
REM
REM Repo root: this .bat lives in src\ac_copilot_trainer\ — two levels up is checkout root.

SET "REPO_ROOT=%~dp0..\.."

REM Ollama coaching env (matches the values that were verified in PR #75).
SET "AC_COPILOT_OLLAMA_ENABLE=1"
SET "AC_COPILOT_OLLAMA_HOST=http://127.0.0.1:11434"
SET "AC_COPILOT_OLLAMA_MODEL=llama3.2:3b"
SET "AC_COPILOT_OLLAMA_TEMPERATURE=0.35"
SET "AC_COPILOT_OLLAMA_NUM_PREDICT=160"
SET "AC_COPILOT_OLLAMA_TIMEOUT_SEC=60"
SET "AC_COPILOT_OLLAMA_DEBRIEF_TIMEOUT_SEC=60"

cd /d "%REPO_ROOT%"
IF NOT EXIST "%REPO_ROOT%\tools\ai_sidecar" (
    echo [start_sidecar] ERROR: tools\ai_sidecar not found at %REPO_ROOT%
    echo [start_sidecar] Expected repo layout: REPO_ROOT\tools\ai_sidecar (REPO_ROOT=%REPO_ROOT%)
    exit /b 2
)

REM Try py -3 first when launcher exists; if it fails at runtime, fall back to python.
where py >nul 2>nul
IF ERRORLEVEL 1 GOTO :USE_PYTHON
py -3 -m tools.ai_sidecar --host 127.0.0.1 --port 8765
IF NOT ERRORLEVEL 1 exit /b 0
echo [start_sidecar] py -3 failed (errorlevel=%ERRORLEVEL%); falling back to python

:USE_PYTHON
python -m tools.ai_sidecar --host 127.0.0.1 --port 8765
exit /b %ERRORLEVEL%
