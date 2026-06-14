param(
    [Parameter(Mandatory=$false)][string]$Workspace = "d:\xiaozhi-esp32-music",
    [Parameter(Mandatory=$false)][string]$EspIdf = "C:\Users\lenovo\esp\v5.4.2\esp-idf",
    [Parameter(Mandatory=$false)][string]$Port = ""
)

$ErrorActionPreference = 'Stop'

# 加载 ESP-IDF 环境
if (-not (Get-Command idf.py -ErrorAction SilentlyContinue)) {
    if (-not (Test-Path $EspIdf)) {
        Write-Error ("ESP-IDF 目录不存在: " + $EspIdf)
    }
    . (Join-Path $EspIdf 'export.ps1')
}

# 切换到工程目录
if (-not (Test-Path $Workspace)) {
    Write-Error ("工程目录不存在: " + $Workspace)
}
Set-Location -Path $Workspace

# 自动检测串口（USB/常见转换芯片）
if ([string]::IsNullOrWhiteSpace($Port)) {
    try {
        $Port = (Get-CimInstance Win32_SerialPort | Where-Object { $_.Caption -match 'USB|CP210|CH340|Silicon|UART' } | Select-Object -First 1 -ExpandProperty DeviceID)
    } catch {}
    if (-not $Port) { $Port = 'COM11' }
}
Write-Host ("使用端口: " + $Port)

# 刷写固件（会自动触发编译）
try {
    idf.py -p $Port flash
} catch {
    exit 2
}
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Start-Sleep -Seconds 1

# 打开串口监视（用户主动结束可能返回非0，这里不当作失败）
try {
    idf.py -p $Port monitor
} catch {
    # 忽略异常
}

exit 0
