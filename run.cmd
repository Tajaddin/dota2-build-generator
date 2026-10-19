@echo off
rem Starts d2bg. Double-click this file, or run:  run.cmd   (extra options go to "d2bg serve")
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0run.ps1" %*
