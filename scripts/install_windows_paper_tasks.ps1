# Register unattended paper ticks (hidden via VBS). LIVE_* stay false inside paper_tick.py.
# Run from the repo: powershell -ExecutionPolicy Bypass -File scripts\install_windows_paper_tasks.ps1
$ErrorActionPreference = "Stop"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$Python = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path $Python)) {
    throw "Missing venv python: $Python"
}
$Tick = Join-Path $Root "scripts\paper_tick.py"
if (-not (Test-Path $Tick)) {
    throw "Missing tick script: $Tick"
}
$Vbs = Join-Path $Root "scripts\run_paper_tick_hidden.vbs"
if (-not (Test-Path $Vbs)) {
    throw "Missing hidden launcher: $Vbs"
}
$Wscript = Join-Path $env:SystemRoot "System32\wscript.exe"
$TaskName = "XSP-Killer-PaperTick"
$EntryName = "XSP-Killer-PaperTick-EntryWindow"

$Action = New-ScheduledTaskAction `
    -Execute $Wscript `
    -Argument "//nologo `"$Vbs`"" `
    -WorkingDirectory $Root
$Settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -WakeToRun `
    -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 12)
$Principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Limited

# Every 15 minutes from now (monitor + entry-if-in-window).
$Repeat = New-ScheduledTaskTrigger -Once -At ((Get-Date).AddMinutes(1)) `
    -RepetitionInterval (New-TimeSpan -Minutes 15) `
    -RepetitionDuration (New-TimeSpan -Days 9999)

# Extra close-window shots so we do not miss 15:50 / 15:55 the way a :00/:15/:30/:45 grid would.
$EntryTriggers = @(
    (New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday,Tuesday,Wednesday,Thursday,Friday -At "3:45PM"),
    (New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday,Tuesday,Wednesday,Thursday,Friday -At "3:50PM"),
    (New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday,Tuesday,Wednesday,Thursday,Friday -At "3:55PM")
)

Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue
Unregister-ScheduledTask -TaskName $EntryName -Confirm:$false -ErrorAction SilentlyContinue

Register-ScheduledTask -TaskName $TaskName -Action $Action -Trigger $Repeat -Settings $Settings -Principal $Principal -Description "XSP Killer paper tick every 15m (hidden). LIVE off." | Out-Null
Register-ScheduledTask -TaskName $EntryName -Action $Action -Trigger $EntryTriggers -Settings $Settings -Principal $Principal -Description "XSP Killer paper entry window 15:45-15:55 ET (hidden). LIVE off." | Out-Null

Write-Host "registered $TaskName and $EntryName via $Vbs"
Get-ScheduledTask -TaskName $TaskName, $EntryName | Format-Table TaskName, State -AutoSize
