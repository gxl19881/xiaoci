param(
    [string]$Port,
    [int]$Baud = 460800,
    [int]$Retries = 2
)

$ErrorActionPreference = 'Stop'
$envScript = 'C:\Users\lenovo\esp\v5.4.2\esp-idf\export.ps1'
if (-not (Test-Path $envScript)) {
    Write-Error ("ESP-IDF export.ps1 not found: {0}" -f $envScript)
    exit 1
}
. $envScript

Set-Location -Path 'd:\xiaozhi-esp32-music'

# Build
idf.py build
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

# Collect candidate serial ports: prefer USB; then all ports; finally COM11 as fallback
$candidates = @()
if ($Port) {
    $candidates += $Port
} else {
    try {
        $usbPorts = Get-CimInstance Win32_SerialPort | Where-Object { $_.Caption -match 'USB' } | Select-Object -ExpandProperty DeviceID
    } catch { $usbPorts = @() }
    if ($usbPorts) { $candidates += $usbPorts }

    try {
        $allPorts = [System.IO.Ports.SerialPort]::GetPortNames() | Sort-Object
    } catch { $allPorts = @() }
    foreach ($p in $allPorts) { if ($candidates -notcontains $p) { $candidates += $p } }

    if ($candidates.Count -eq 0) { $candidates += 'COM11' }
}

Write-Host ("Candidates: {0}" -f ($candidates -join ', '))

function Test-Port-Free([string]$p) {
    try {
        $sp = New-Object System.IO.Ports.SerialPort($p, 115200)
        $sp.ReadTimeout = 200
        $sp.WriteTimeout = 200
        $sp.Open()
        $sp.Close()
        return $true
    } catch {
        return $false
    }
}

function Try-Flash-And-Monitor([string]$p) {
    Write-Host ("Trying port: {0} at {1} baud" -f $p, $Baud)
    for ($i = 0; $i -le $Retries; $i++) {
        if (-not (Test-Port-Free $p)) {
            Write-Warning ("Port {0} appears busy, retry {1}/{2}" -f $p, $i, $Retries)
            Start-Sleep -Seconds 2
            continue
        }
        idf.py -p $p -b $Baud flash
        if ($LASTEXITCODE -eq 0) { break }
        Write-Warning ("Flash attempt {0}/{1} failed on {2}, retrying..." -f ($i+1), ($Retries+1), $p)
        Start-Sleep -Seconds 2
    }
    if ($LASTEXITCODE -ne 0) {
        Write-Warning ("Flash failed on port {0}, trying next (busy or missing)" -f $p)
        return $false
    }
    Start-Sleep -Seconds 1
    idf.py -p $p monitor
    return $true
}

$ok = $false
foreach ($p in $candidates) {
    if (Try-Flash-And-Monitor $p) { $ok = $true; break }
}

if (-not $ok) {
    Write-Error 'Flashing failed on all ports. Ensure: 1) no other serial monitor is open; 2) device is connected; 3) port is correct.'
    exit 1
}
