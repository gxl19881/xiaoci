$ErrorActionPreference = "Stop"
Write-Host "Setting up ESP-IDF environment..."
$env:PATH = "D:\.espressif\python_env\idf5.4_py3.11_env\Scripts;" + $env:PATH
$env:IDF_TOOLS_PATH = "D:\.espressif"

if (-not (Test-Path "D:\esp-idf5.4.3\v5.4.3\esp-idf\export.ps1")) {
    Write-Error "ESP-IDF export script not found at D:\esp-idf5.4.3\v5.4.3\esp-idf\export.ps1"
    exit 1
}

. "D:\esp-idf5.4.3\v5.4.3\esp-idf\export.ps1"

Set-Location "E:\xiaozhi-esp32-music-K10"

Write-Host "Building project..."
idf.py build

if ($LASTEXITCODE -eq 0) {
    Write-Host "Erasing flash to clear old settings..."
    idf.py -p COM8 erase_flash
    Write-Host "Flashing and Monitoring on COM8..."
    idf.py -p COM8 flash monitor
} else {
    Write-Error "Build failed."
}
