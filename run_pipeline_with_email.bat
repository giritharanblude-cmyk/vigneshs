@echo off
REM Soft-Skill AI Trends Pipeline - Daily Run Script with Email Configuration
cd /d "%~dp0"

REM Load email configuration from email_config.env
for /f "usebackq tokens=1,* delims==" %%a in ("email_config.env") do set "%%a=%%b"

REM Run the pipeline with email enabled
echo [%date% %time%] Starting pipeline...
python main.py
echo [%date% %time%] Pipeline completed.
echo %date% %time% - Pipeline run completed >> pipeline_log.txt
