param(
    [ValidateSet('start', 'stop', 'status', 'update')]
    [string]$Action = 'start',
    [string]$BindAddress = '127.0.0.1',
    [ValidateRange(1, 65535)]
    [int]$Port = 8000
)

$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$pythonPath = Join-Path $projectRoot '.venv\Scripts\python.exe'
$runtimeDir = Join-Path $projectRoot '.cache\deploy'
$pidFile = Join-Path $runtimeDir 'server.pid'
$outFile = Join-Path $runtimeDir 'server.out.log'
$errFile = Join-Path $runtimeDir 'server.err.log'

function Invoke-Checked {
    param([string]$File, [string[]]$Arguments)
    & $File @Arguments
    if ($LASTEXITCODE -ne 0) { throw "$File exited with code $LASTEXITCODE" }
}

function Get-ServerProcess {
    if (!(Test-Path -LiteralPath $pidFile)) { return $null }
    $serverPid = [int](Get-Content -LiteralPath $pidFile -Encoding utf8)
    $server = Get-CimInstance Win32_Process -Filter "ProcessId = $serverPid"
    if ($null -eq $server) { return $null }
    if ($server.CommandLine -notlike '*deploy.gateway:create_app*' -or
        $server.ExecutablePath -ine $pythonPath) {
        throw "PID $serverPid does not belong to this deployment. Check $pidFile."
    }
    return $server
}

function Stop-Server {
    $server = Get-ServerProcess
    if ($null -ne $server) {
        # Stop the venv launcher and its interpreter child together.
        Invoke-Checked -File 'taskkill.exe' -Arguments @('/PID', [string]$server.ProcessId, '/T', '/F')
    }
    if (Test-Path -LiteralPath $pidFile) { Remove-Item -LiteralPath $pidFile }
}

function Install-Dependencies {
    if (!(Test-Path -LiteralPath $pythonPath)) {
        Invoke-Checked -File 'python' -Arguments @('-m', 'venv', (Join-Path $projectRoot '.venv'))
    }
    Invoke-Checked -File $pythonPath -Arguments @('-m', 'pip', 'install', '-r', (Join-Path $projectRoot 'requirements.txt'))
}

function Start-Server {
    if ($null -ne (Get-ServerProcess)) { throw 'Already running. Use status or stop.' }
    if (!(Test-Path -LiteralPath (Join-Path $projectRoot '.env'))) {
        throw 'Create .env using the deployment section in README.md first.'
    }
    New-Item -ItemType Directory -Path $runtimeDir -Force | Out-Null
    $server = Start-Process -FilePath $pythonPath -ArgumentList @(
        '-m', 'uvicorn', 'deploy.gateway:create_app', '--factory',
        '--host', $BindAddress, '--port', $Port, '--workers', '1', '--no-proxy-headers'
    ) -WorkingDirectory $projectRoot -WindowStyle Hidden -PassThru `
      -RedirectStandardOutput $outFile -RedirectStandardError $errFile
    Set-Content -LiteralPath $pidFile -Value $server.Id -Encoding utf8
    $probeAddress = if ($BindAddress -eq '0.0.0.0') { '127.0.0.1' } else { $BindAddress }
    $probeUrl = "http://${probeAddress}:$Port"
    try {
        Invoke-Checked -File $pythonPath -Arguments @(
            (Join-Path $PSScriptRoot 'smoke.py'), '--base-url', $probeUrl, '--ready', '--wait'
        )
        $server.Refresh()
        if ($server.HasExited) { throw "Startup failed. Read $errFile" }
    }
    catch {
        Stop-Server
        throw
    }
    Write-Output "Started: $probeUrl (PID $($server.Id))"
}

Push-Location $projectRoot
try {
    switch ($Action) {
        'start' { Install-Dependencies; Start-Server }
        'stop' { Stop-Server; Write-Output 'Stopped.' }
        'status' {
            $server = Get-ServerProcess
            if ($null -eq $server) { Write-Output 'Stopped.' }
            else { Write-Output "Running: PID $($server.ProcessId). Logs: $runtimeDir" }
        }
        'update' {
            $dirty = & git status --porcelain --untracked-files=no
            if ($LASTEXITCODE -ne 0) { throw 'git status failed.' }
            if ($dirty) { throw 'Commit tracked changes before updating.' }
            Invoke-Checked -File 'git' -Arguments @('pull', '--ff-only')
            Install-Dependencies
            Invoke-Checked -File $pythonPath -Arguments @('-m', 'pytest', '-q')
            Stop-Server
            Start-Server
        }
    }
}
finally { Pop-Location }
