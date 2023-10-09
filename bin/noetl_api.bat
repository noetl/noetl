@echo off
setlocal enabledelayedexpansion

set "CURPATH=%~dp0"
set "NOETL_API_PATH=!CURPATH!\..\noetl\api.py"
set HOST=localhost
set PORT=8021


python "!NOETL_API_PATH!" --host %HOST% --port %PORT%
endlocal
