param([string]$Python = "python")
$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$buildWork = Join-Path ([IO.Path]::GetTempPath()) ("kanshan-build-" + [guid]::NewGuid().ToString("N"))
Push-Location $projectRoot
try {
    & $Python -m PyInstaller --noconfirm --clean --onedir --windowed --workpath $buildWork --name "看山谜案馆" --icon "desktop/kanshan.ico" --add-data "frontend;frontend" --add-data "stories;stories" --add-data "desktop/ui;desktop/ui" --add-data "desktop/kanshan.ico;desktop" --collect-all webview --collect-all pythonnet --collect-all clr_loader --hidden-import uvicorn.logging --hidden-import uvicorn.loops.auto --hidden-import uvicorn.protocols.http.auto --hidden-import uvicorn.protocols.websockets.auto --hidden-import uvicorn.lifespan.on --paths . desktop/main.py
    if ($LASTEXITCODE -ne 0) { throw "PyInstaller 打包失败。" }
    Write-Host "桌面版已生成：$projectRoot\dist\看山谜案馆\看山谜案馆.exe"
} finally { Pop-Location }
