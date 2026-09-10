@echo off
REM Soft-Skill AI Trends Pipeline - Daily Run Script
REM This script runs the pipeline and sends email reports

cd /d "%~dp0"

REM Set email configuration (update these values with your credentials)
REM For Gmail: Generate App Password at https://myaccount.google.com/apppasswords
set SMTP_HOST=smtp.gmail.com
set SMTP_PORT=587
set EMAIL_USERNAME=YOUR_EMAIL@gmail.com
set EMAIL_PASSWORD=YOUR_APP_PASSWORD
set DASHBOARD_URL=http://localhost:8000/dashboard/

REM Run the pipeline
echo [%date% %time%] Starting pipeline...
python main.py
echo [%date% %time%] Pipeline completed.

REM Log the run
echo %date% %time% - Pipeline run completed >> pipeline_log.txt
