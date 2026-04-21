@echo off
setlocal EnableDelayedExpansion
REM ac-copilot-trainer Python sidecar launcher (issue #77 part A)
REM Auto-spawned by ws_bridge.lua via os.runConsoleProcess at app load.
REM
REM Finds repo root by walking up from this .bat until tools\ai_sidecar exists
REM (works for git checkout src\ac_copilot_trainer\ and CSP deploy under apps\lua\...).
REM Optional: set AC_COPILOT_REPO_ROOT to your checkout if search fails.

if defined AC_COPILOT_REPO_ROOT (
  if exist "!AC_COPILOT_REPO_ROOT!\tools\ai_sidecar\" (
    set "REPO_ROOT=!AC_COPILOT_REPO_ROOT!"
    goto :have_root
  )
)

set "CUR=%~dp0"
if "!CUR:~-1!"=="\" set "CUR=!CUR:~0,-1!"
for /L %%n in (1,1,28) do (
  if exist "!CUR!\tools\ai_sidecar\" (
    set "REPO_ROOT=!CUR!"
    goto :have_root
  )
  for %%P in ("!CUR!\..") do set "NXT=%%~fP"
  if "!NXT!"=="!CUR!" goto :no_repo
  set "CUR=!NXT!"
)
:no_repo
echo [start_sidecar] ERROR: tools\ai_sidecar not found walking up from %~dp0
echo [start_sidecar] Set AC_COPILOT_REPO_ROOT to your repo root, or deploy the full checkout.
exit /b 2

:have_root
REM Ollama coaching env (matches the values that were verified in PR #75).
SET "AC_COPILOT_OLLAMA_ENABLE=1"
SET "AC_COPILOT_OLLAMA_HOST=http://127.0.0.1:11434"
SET "AC_COPILOT_OLLAMA_MODEL=llama3.2:3b"
SET "AC_COPILOT_OLLAMA_TEMPERATURE=0.35"
SET "AC_COPILOT_OLLAMA_NUM_PREDICT=160"
SET "AC_COPILOT_OLLAMA_TIMEOUT_SEC=60"
SET "AC_COPILOT_OLLAMA_DEBRIEF_TIMEOUT_SEC=60"

cd /d "!REPO_ROOT!"
IF NOT EXIST "!REPO_ROOT!\tools\ai_sidecar" (
    echo [start_sidecar] ERROR: tools\ai_sidecar missing under !REPO_ROOT!
    exit /b 2
)

where py >nul 2>nul
IF ERRORLEVEL 1 GOTO :USE_PYTHON
py -3 -m tools.ai_sidecar --host 127.0.0.1 --port 8765
IF NOT ERRORLEVEL 1 exit /b 0
echo [start_sidecar] py -3 failed (errorlevel=%ERRORLEVEL%); falling back to python

:USE_PYTHON
python -m tools.ai_sidecar --host 127.0.0.1 --port 8765
exit /b %ERRORLEVEL%
