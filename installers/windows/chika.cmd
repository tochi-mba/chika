@echo off
:: ─────────────────────────────────────────────────────────────────────────
::  Chika launcher — installed at <InstallDir>\chika.cmd
::
::  Forwards every argument to the venv's chika.exe. Sets a couple of
::  env vars so user state lives in %USERPROFILE%\.chika\ — that
::  directory survives Add/Remove Programs uninstall, so settings,
::  profiles, and chat history persist across reinstalls.
::
::  CHIKA_SETTINGS_PATH points the runtime settings file into
::  ~/.chika/data/settings.json.
::
::  CHIKA_DATA_DIR is exported for any future state file that opts
::  into the same persisted-across-uninstalls pattern (chat history,
::  profile dir, etc.). settings_store reads CHIKA_SETTINGS_PATH
::  first, falls back to CHIKA_DATA_DIR + "/settings.json".
::
::  We don't `set` these globally — they apply only to the chika
::  process tree, so other terminals are unaffected.
:: ─────────────────────────────────────────────────────────────────────────
setlocal

if "%CHIKA_DATA_DIR%"=="" set "CHIKA_DATA_DIR=%USERPROFILE%\.chika\data"
if "%CHIKA_SETTINGS_PATH%"=="" set "CHIKA_SETTINGS_PATH=%CHIKA_DATA_DIR%\settings.json"

if not exist "%CHIKA_DATA_DIR%" mkdir "%CHIKA_DATA_DIR%" >nul 2>&1

"%~dp0venv\Scripts\chika.exe" %*
exit /b %ERRORLEVEL%
