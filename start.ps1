<#
.SYNOPSIS
  Start Flowboard with one command: agent + frontend.

.DESCRIPTION
  Run it after a reboot or after changing code. It:
    1. writes the Flow project / plan into .env when you pass them,
    2. stops a Flowboard agent/frontend still running from before,
    3. installs Python / frontend dependencies when they changed,
    4. starts the frontend in the background and the agent in this terminal,
    5. once the agent is up, moves every board onto the .env Flow project when
       that project changed (boards keep their own binding, so editing .env
       alone would leave them generating into the old project).
  Ctrl+C stops both. Keep Chrome open and signed in to flow.google.com, with
  the Flowboard extension on and the Flow Kit extension off.

.EXAMPLE
  .\start.ps1                          # reuse the Flow project in .env
.EXAMPLE
  .\start.ps1 -FlowProjectId <uuid>    # switch Flow project (written to .env)
.EXAMPLE
  .\start.ps1 -Plan Ultra              # Flow plan: Pro or Ultra (written to .env)
.EXAMPLE
  .\start.ps1 -NoFrontend              # agent only
#>
param(
    [string]$FlowProjectId,
    [ValidateSet('Pro', 'Ultra')][string]$Plan,
    [switch]$NoFrontend
)

$ErrorActionPreference = 'Stop'
$root = $PSScriptRoot
$agentDir = Join-Path $root 'agent'
$frontDir = Join-Path $root 'frontend'
$envFile = Join-Path $root '.env'
$stateFile = Join-Path $root '.fb-start.json'   # gitignored: last pinned project + install fingerprints
$logDir = Join-Path $root 'storage\logs'
$agentPort = 8434   # also hardcoded in extension/ and frontend/vite.config.ts
$wsPort = 8355      # FLOWBOARD_EXT_WS_PORT; also hardcoded in extension/
$frontPort = 5174   # not Vite's 5173, so Flow Kit's dashboard can run alongside
$api = "http://127.0.0.1:$agentPort"
$uuidRe = '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
Set-Location $root

function Step([string]$msg) { Write-Host "==> $msg" -ForegroundColor Cyan }

# A terminal inside an editor (VS Code, Cursor) inherits the PATH the editor
# had when it launched, so a CLI installed since then (agy, codex, ffmpeg…)
# is invisible to the agent even in a brand-new terminal tab. Append whatever
# the registry PATH has that this session lacks; never drop session entries.
$known = @($env:Path -split ';' | Where-Object { $_ } | ForEach-Object { $_.TrimEnd('\') })
foreach ($scope in 'Machine', 'User') {
    foreach ($dir in ([Environment]::GetEnvironmentVariable('Path', $scope) -split ';')) {
        if (-not $dir) { continue }
        $dir = [Environment]::ExpandEnvironmentVariables($dir)
        if ($known -notcontains $dir.TrimEnd('\')) {
            $env:Path += ";$dir"
            $known += $dir.TrimEnd('\')
        }
    }
}

function Get-Fingerprint([string[]]$paths) {
    ($paths | ForEach-Object { (Get-FileHash $_ -Algorithm SHA256).Hash }) -join ''
}

$state = @{}
if (Test-Path $stateFile) {
    (Get-Content $stateFile -Raw | ConvertFrom-Json).PSObject.Properties |
        ForEach-Object { $state[$_.Name] = $_.Value }
}
function Save-State { $state | ConvertTo-Json | Set-Content $stateFile -Encoding UTF8 }

# .env is read by the agent itself; write it without a BOM so the first key parses.
function Get-EnvValue([string]$key) {
    if (-not (Test-Path $envFile)) { return $null }
    $line = Get-Content $envFile -Encoding UTF8 | Where-Object { $_ -match "^\s*$key=" } | Select-Object -Last 1
    if (-not $line) { return $null }
    # Same parsing as agent/flowboard/config.py: trimmed, one pair of quotes off.
    $value = ($line -split '=', 2)[1].Trim()
    if ($value.Length -ge 2 -and $value[0] -eq $value[-1] -and "$($value[0])" -in @('"', "'")) {
        $value = $value.Substring(1, $value.Length - 2)
    }
    return $value
}
function Set-EnvValue([string]$key, [string]$value) {
    $found = $false
    $lines = @(Get-Content $envFile -Encoding UTF8 | ForEach-Object {
        if ($_ -match "^\s*$key=") { $found = $true; "$key=$value" } else { $_ }
    })
    if (-not $found) { $lines += "$key=$value" }
    [IO.File]::WriteAllLines($envFile, [string[]]$lines, (New-Object Text.UTF8Encoding $false))
}

# Stop whatever of ours still holds a port; refuse to touch anyone else's.
# "Ours" includes a process whose parent is ours: under `uvicorn --reload`
# the port is held by a multiprocessing child whose own command line does
# not name flowboard.
function Stop-OldCopy([int]$port, [string]$pattern, [switch]$Required) {
    $owners = Get-NetTCPConnection -State Listen -LocalPort $port -ErrorAction SilentlyContinue |
        Select-Object -ExpandProperty OwningProcess -Unique
    foreach ($procId in $owners) {
        $proc = Get-CimInstance Win32_Process -Filter "ProcessId=$procId"
        if (-not $proc) { continue }
        $parent = Get-CimInstance Win32_Process -Filter "ProcessId=$($proc.ParentProcessId)"
        $parentMine = $parent -and $parent.CommandLine -like $pattern
        if (-not ($proc.CommandLine -like $pattern -or $parentMine)) {
            if ($Required) { throw "Port $port is used by another program ($($proc.Name), PID $procId). Close it and retry." }
            continue
        }
        Step "Stopping old $($proc.Name) on port $port (PID $procId)"
        cmd /c "taskkill /PID $procId /T /F >nul 2>&1"
        if ($parentMine) { cmd /c "taskkill /PID $($parent.ProcessId) /T /F >nul 2>&1" }
    }
    for ($i = 0; $i -lt 40 -and (Get-NetTCPConnection -State Listen -LocalPort $port -ErrorAction SilentlyContinue); $i++) {
        Start-Sleep -Milliseconds 250
    }
}

# -- 1. .env: Flow project + plan --------------------------------------------
if (-not (Test-Path $envFile)) {
    Step 'Creating .env from .env.example'
    Copy-Item (Join-Path $root '.env.example') $envFile
}
if ($FlowProjectId) {
    if ($FlowProjectId -notmatch $uuidRe) {
        throw 'FlowProjectId must be the uuid from the Flow project URL (flow.google.com/.../<uuid>)'
    }
    Set-EnvValue 'FLOWBOARD_FLOW_PROJECT_ID' $FlowProjectId.ToLower()
}
if ($Plan) {
    $tier = 'PAYGATE_TIER_ONE'
    if ($Plan -eq 'Ultra') { $tier = 'PAYGATE_TIER_TWO' }
    Set-EnvValue 'FLOWBOARD_PAYGATE_TIER' $tier
}
$projectId = Get-EnvValue 'FLOWBOARD_FLOW_PROJECT_ID'
if ($projectId) { $projectId = $projectId.ToLower() }
$tier = Get-EnvValue 'FLOWBOARD_PAYGATE_TIER'
if (-not ($projectId -match $uuidRe)) {
    Write-Warning 'No valid Flow project in .env. Run once: .\start.ps1 -FlowProjectId <uuid from the Flow project URL>'
    $projectId = $null
}
if ($tier -notin @('PAYGATE_TIER_ONE', 'PAYGATE_TIER_TWO')) {
    Write-Warning 'No Flow plan in .env. Run once: .\start.ps1 -Plan Pro   (or -Plan Ultra)'
}

# -- 2. Old copies -----------------------------------------------------------
Stop-OldCopy $agentPort '*flowboard.main*' -Required
Stop-OldCopy $wsPort '*flowboard.main*' -Required
if (-not $NoFrontend) {
    Stop-OldCopy 5173 "*$frontDir*"   # an old hand-started copy from before Vite was pinned to 5174
    Stop-OldCopy $frontPort "*$frontDir*" -Required
}

# -- 3. Dependencies (only when they changed) --------------------------------
$uv = Get-Command uv -ErrorAction SilentlyContinue
$py = Join-Path $agentDir '.venv\Scripts\python.exe'
if (-not (Test-Path $py)) {
    Step 'Creating agent\.venv'
    Push-Location $agentDir
    if ($uv) { uv venv --python 3.11 .venv } else { py -3.11 -m venv .venv }
    $code = $LASTEXITCODE
    Pop-Location
    if ($code) { throw 'Could not create agent\.venv - is Python 3.11+ installed?' }
}
$reqHash = Get-Fingerprint (Join-Path $agentDir 'pyproject.toml')
if ($state.requirements -ne $reqHash) {
    Step 'Installing Python dependencies'
    if ($uv) { uv pip install --python $py -q -e $agentDir } else { & $py -m pip install -q -e $agentDir }
    if ($LASTEXITCODE) { throw 'Python dependency install failed' }
    $state.requirements = $reqHash
    Save-State
}
if (-not $NoFrontend) {
    $lock = Join-Path $frontDir 'package-lock.json'
    if (-not (Test-Path (Join-Path $frontDir 'node_modules')) -or $state.frontend_lock -ne (Get-Fingerprint $lock)) {
        Step 'Installing frontend dependencies'
        Push-Location $frontDir
        npm.cmd install --no-audit --no-fund
        $code = $LASTEXITCODE
        Pop-Location
        if ($code) { throw 'npm install failed' }
        $state.frontend_lock = Get-Fingerprint $lock   # npm may rewrite the lock
        Save-State
    }
}
if (-not (Get-Command ffmpeg -ErrorAction SilentlyContinue)) {
    Write-Warning 'ffmpeg is not on PATH (needed to join clips)'
}
# Auto-prompt / vision / planner / chat need at least one AI CLI.
$clis = @('claude', 'agy', 'codex') | Where-Object { Get-Command $_ -ErrorAction SilentlyContinue }
if ($clis) { Step "AI CLIs found: $($clis -join ', ')" }
else { Write-Warning 'No AI CLI on PATH (claude / agy / codex) - auto-prompt, vision and chat will fail' }

# -- 4. Frontend (background) ------------------------------------------------
$front = $null
if (-not $NoFrontend) {
    New-Item -ItemType Directory -Force $logDir | Out-Null
    $frontArgs = @{
        FilePath               = 'npm.cmd'
        ArgumentList           = 'run', 'dev', '--', '--port', "$frontPort", '--strictPort'
        WorkingDirectory       = $frontDir
        WindowStyle            = 'Hidden'
        PassThru               = $true
        RedirectStandardOutput = Join-Path $logDir 'frontend.log'
        RedirectStandardError  = Join-Path $logDir 'frontend.err.log'
    }
    $front = Start-Process @frontArgs
}

# -- 5. Extension: no remote reload in Flowboard, so just say when it changed -
$extFiles = Get-ChildItem (Join-Path $root 'extension') -Recurse -File |
    Where-Object { $_.FullName -notlike '*\_metadata\*' } | Sort-Object FullName
$extHash = Get-Fingerprint $extFiles.FullName
$extChanged = $state.extension -ne $extHash
if ($extChanged) {
    $state.extension = $extHash
    Save-State   # last write from here on; the pin job below owns the file after this
}

# -- 6. Move boards onto the .env project, once the agent is up --------------
# A board stores the project it first generated into, and only the pinned-
# project endpoint moves those bindings. So when the .env project changed since
# the last start, pin it through the API, which rebinds every board.
$pinJob = $null
if ($projectId -and $state.flow_project_id -ne $projectId) {
    $pinJob = Start-Job -ArgumentList $api, $stateFile, $projectId -ScriptBlock {
        param($api, $stateFile, $projectId)
        $up = $false
        for ($i = 0; $i -lt 90 -and -not $up; $i++) {
            Start-Sleep 1
            try { $up = (Invoke-RestMethod "$api/api/health" -UseBasicParsing -TimeoutSec 3).ok } catch { }
        }
        if (-not $up) { return }
        $body = @{ flow_project_id = $projectId } | ConvertTo-Json
        Invoke-RestMethod "$api/api/flow/projects/pinned" -Method Put -Body $body `
            -ContentType 'application/json' -UseBasicParsing | Out-Null
        $saved = if (Test-Path $stateFile) { Get-Content $stateFile -Raw | ConvertFrom-Json } else { New-Object psobject }
        $saved | Add-Member -NotePropertyName flow_project_id -NotePropertyValue $projectId -Force
        $saved | ConvertTo-Json | Set-Content $stateFile -Encoding UTF8
    }
}

# -- 7. Agent (foreground) ---------------------------------------------------
Write-Host ''
Write-Host 'Flowboard' -ForegroundColor Green
if ($projectId) { Write-Host "  Flow project : $projectId" }
if ($tier) { Write-Host "  Flow plan    : $tier" }
Write-Host "  API          : $api   (try it: $api/docs)"
if ($front) { Write-Host "  App          : http://localhost:$frontPort   (log: storage\logs\frontend.log)" }
if ($pinJob) { Write-Host '  Boards       : will be moved onto this Flow project once the agent is up' }
if ($extChanged) {
    Write-Host '  Extension    : changed - reload "Flowboard Bridge" in chrome://extensions, then F5 the Flow tab' -ForegroundColor Yellow
}
Write-Host '  Chrome       : Flowboard extension ON, Flow Kit extension OFF, one flow.google.com tab open'
Write-Host '  Stop         : Ctrl+C'
Write-Host ''

Push-Location $agentDir
try {
    & $py -m uvicorn flowboard.main:app --host 127.0.0.1 --port $agentPort --timeout-graceful-shutdown 2
} finally {
    Pop-Location
    if ($front) { cmd /c "taskkill /PID $($front.Id) /T /F >nul 2>&1" }
    if ($pinJob) { Remove-Job $pinJob -Force }
}
