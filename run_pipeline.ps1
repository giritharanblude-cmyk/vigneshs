# Soft-Skill AI Trends Pipeline - PowerShell Runner with Email
Set-Location $PSScriptRoot

# Load email configuration
Get-Content "email_config.env" | ForEach-Object {
    if ($_ -match "^(.+?)=(.+)$") {
        [Environment]::SetEnvironmentVariable($matches[1].Trim(), $matches[2].Trim(), "Process")
    }
}

Write-Host "[$(Get-Date)] Starting pipeline..."
python main.py
Write-Host "[$(Get-Date)] Pipeline completed."
"$(Get-Date) - Pipeline run completed" | Out-File -Append "pipeline_log.txt"
