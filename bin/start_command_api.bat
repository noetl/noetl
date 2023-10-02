@echo off
setlocal enabledelayedexpansion

set "CURPATH=%~dp0"
set "COMMAND_PATH=!CURPATH!\..\noetl\command.py"
set HOST=localhost
set PORT=8021


python "!COMMAND_PATH!" --host %HOST% --port %PORT%
endlocal
