@echo off
rem Starts the Streamlit UI with the GnuCOBOL environment the COBOL oracle needs.
rem GnuCOBOL is not on PATH globally; set_env.cmd adds it for this window only.
rem Usage: run_ui.cmd [extra streamlit args, e.g. --server.port 8502]
call "%USERPROFILE%\tools\gnucobol\set_env.cmd" >nul
cd /d "%~dp0"
python -m streamlit run streamlit_app.py %*
