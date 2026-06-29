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
REM Ollama coaching env (defaults from PR #75). Do not override user-set vars (inheritEnvironment=true).
if not defined AC_COPILOT_OLLAMA_ENABLE set "AC_COPILOT_OLLAMA_ENABLE=1"
if not defined AC_COPILOT_OLLAMA_HOST set "AC_COPILOT_OLLAMA_HOST=http://127.0.0.1:11434"
if not defined AC_COPILOT_OLLAMA_MODEL set "AC_COPILOT_OLLAMA_MODEL=llama3.2:3b"
if not defined AC_COPILOT_OLLAMA_TEMPERATURE set "AC_COPILOT_OLLAMA_TEMPERATURE=0.35"
if not defined AC_COPILOT_OLLAMA_NUM_PREDICT set "AC_COPILOT_OLLAMA_NUM_PREDICT=160"
if not defined AC_COPILOT_OLLAMA_TIMEOUT_SEC set "AC_COPILOT_OLLAMA_TIMEOUT_SEC=60"
if not defined AC_COPILOT_OLLAMA_DEBRIEF_TIMEOUT_SEC set "AC_COPILOT_OLLAMA_DEBRIEF_TIMEOUT_SEC=60"
if not defined AC_COPILOT_SIDECAR_PORT set "AC_COPILOT_SIDECAR_PORT=8765"
if "!AC_COPILOT_SIDECAR_PORT!"=="" set "AC_COPILOT_SIDECAR_PORT=8765"

cd /d "!REPO_ROOT!"
IF NOT EXIST "!REPO_ROOT!\tools\ai_sidecar" (
    echo [start_sidecar] ERROR: tools\ai_sidecar missing under !REPO_ROOT!
    exit /b 2
)

REM Default remains loopback-only for normal in-game Lua use. When the rig-screen
REM token is present, expose the sidecar on the LAN/hotspot while keeping the
REM token in the child process environment instead of the process command line.
set "SIDECAR_ARGS=--host 127.0.0.1 --port !AC_COPILOT_SIDECAR_PORT!"
if not "!AC_COPILOT_SIDECAR_TOKEN!"=="" (
  if not defined AC_COPILOT_SIDECAR_EXTERNAL_BIND set "AC_COPILOT_SIDECAR_EXTERNAL_BIND=0.0.0.0"
  if "!AC_COPILOT_SIDECAR_EXTERNAL_BIND!"=="" set "AC_COPILOT_SIDECAR_EXTERNAL_BIND=0.0.0.0"
  set "SIDECAR_ARGS=--external-bind !AC_COPILOT_SIDECAR_EXTERNAL_BIND! --port !AC_COPILOT_SIDECAR_PORT!"
) else (
  if not "!AC_COPILOT_SIDECAR_EXTERNAL_BIND!"=="" (
    echo [start_sidecar] WARNING: AC_COPILOT_SIDECAR_EXTERNAL_BIND ignored because AC_COPILOT_SIDECAR_TOKEN is unset.
  )
)

where py >nul 2>nul
IF ERRORLEVEL 1 GOTO :USE_PYTHON
py -3 -m tools.ai_sidecar !SIDECAR_ARGS!
set "EC=!ERRORLEVEL!"
if "!EC!"=="0" exit /b 0
echo [start_sidecar] py -3 sidecar exited (errorlevel=!EC!); not retrying with a different python.exe
REM Bugbot #78: `IF ERRORLEVEL 1` can miss NTSTATUS-style crash codes; any non-zero EC is failure.
if "!EC!"=="2" exit /b 2
if "!EC!" LSS "0" exit /b 1
exit /b !EC!

:USE_PYTHON
python -m tools.ai_sidecar !SIDECAR_ARGS!
set "EC=!ERRORLEVEL!"
if "!EC!"=="0" exit /b 0
echo [start_sidecar] python sidecar exited (errorlevel=!EC!)
if "!EC!"=="2" exit /b 2
if "!EC!" LSS "0" exit /b 1
exit /b !EC!
