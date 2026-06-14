param(
    [Parameter(Mandatory=$false)][string]$Workspace = "d:\xiaozhi-esp32-music",
    [Parameter(Mandatory=$false)][string]$EspIdf = "C:\Users\lenovo\esp\v5.4.2\esp-idf"
)

$ErrorActionPreference = 'Stop'

# 确保已加载 ESP-IDF 环境
if (-not (Get-Command idf.py -ErrorAction SilentlyContinue)) {
    if (-not (Test-Path $EspIdf)) {
        throw ("ESP-IDF 目录不存在: " + $EspIdf)
    }
    . (Join-Path $EspIdf 'export.ps1')
}

# 切换到工程目录
if (-not (Test-Path $Workspace)) {
    throw ("工程目录不存在: " + $Workspace)
}
Set-Location -Path $Workspace

# 构建
idf.py build
exit $LASTEXITCODE
