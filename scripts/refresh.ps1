# Nightly catalog refresh for PaLiquor (Windows Task Scheduler friendly).
# Re-scrapes the catalog (history accrues) and fires due alerts.
#
# Register as a daily 3 AM task (run once, in this repo's root):
#   $action  = New-ScheduledTaskAction -Execute "powershell.exe" `
#       -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$PWD\scripts\refresh.ps1`""
#   $trigger = New-ScheduledTaskTrigger -Daily -At 3am
#   Register-ScheduledTask -TaskName "PaLiquor nightly refresh" -Action $action -Trigger $trigger

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$py = Join-Path $root ".venv\Scripts\python.exe"

& $py -m paliquor.cli refresh-catalog --categories 152,156,157,159,158,153,160,161,162
& $py -m paliquor.cli check-alerts
