@echo off
REM ORT Web launcher for Windows
SET DIR=%~dp0
"%DIR%.venv\Scripts\python.exe" -m app.cli %*
