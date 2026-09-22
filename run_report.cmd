@echo off
rem Runs every pipeline scope and writes out\pipeline_report.html.
rem Sets up the GnuCOBOL environment first, same as run_ui.cmd.
call "%USERPROFILE%\tools\gnucobol\set_env.cmd" >nul
cd /d "%~dp0"
python make_report.py %*
