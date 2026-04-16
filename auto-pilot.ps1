# ============================================================
# AUTO-PILOT for Claude Code
# Cycles through prompts while you sleep
# Usage: powershell -ExecutionPolicy Bypass -File "auto-pilot.ps1"
# Stop:  Ctrl+C or close the terminal
# ============================================================

# --- CONFIG ---
$prompts = @("continue", "repeat", "grow")
$waitMinutes = 10          # minutes between each send
$jitterSeconds = 30        # random jitter 0..N seconds added to wait
$windowTitle = "Claude"    # partial match for the Claude Code window title
# --- END CONFIG ---

Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName Microsoft.VisualBasic

$i = 0
Write-Host "=== Auto-Pilot Started ===" -ForegroundColor Cyan
Write-Host "Prompts : $($prompts -join ', ')"
Write-Host "Interval: ~$waitMinutes min (+ up to ${jitterSeconds}s jitter)"
Write-Host "Target  : window containing '$windowTitle'"
Write-Host "Press Ctrl+C to stop.`n"

while ($true) {
    $prompt = $prompts[$i % $prompts.Count]
    $timestamp = Get-Date -Format "HH:mm:ss"

    # Try to activate the Claude Code window
    $activated = [Microsoft.VisualBasic.Interaction]::AppActivate($windowTitle)

    if (-not $activated) {
        Write-Host "[$timestamp] WARNING: Could not find window '$windowTitle' - retrying in 30s" -ForegroundColor Yellow
        Start-Sleep -Seconds 30
        continue
    }

    Start-Sleep -Milliseconds 500  # let window come to front

    # Type the prompt and press Enter
    [System.Windows.Forms.SendKeys]::SendWait($prompt)
    Start-Sleep -Milliseconds 200
    [System.Windows.Forms.SendKeys]::SendWait("{ENTER}")

    Write-Host "[$timestamp] Sent #$($i+1): '$prompt'" -ForegroundColor Green

    $i++

    # Wait with jitter
    $jitter = Get-Random -Minimum 0 -Maximum $jitterSeconds
    $totalWait = ($waitMinutes * 60) + $jitter
    Write-Host "           Waiting $([math]::Round($totalWait/60,1)) min until next send..."
    Start-Sleep -Seconds $totalWait
}
