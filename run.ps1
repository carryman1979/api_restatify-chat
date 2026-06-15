param(
    [ValidateSet("standalone", "docker")]
    [string]$Mode = "standalone",
    [string]$ApiHost = "127.0.0.1",
    [int]$Port = 8089
)

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ScriptDir

function Ensure-EnvFile {
    if (-not (Test-Path ".env")) {
        Copy-Item ".env.example" ".env"
        Write-Host "Created .env from .env.example"
    }
}

function Run-Standalone {
    Ensure-EnvFile

    if (-not (Test-Path ".venv")) {
        python -m venv .venv
    }

    & .\.venv\Scripts\python.exe -m pip install -e .
    & .\.venv\Scripts\python.exe -m uvicorn src.app.main:app --app-dir "$ScriptDir" --host "$ApiHost" --port "$Port" --reload
}

function Run-Docker {
    Ensure-EnvFile
    docker compose up --build
}

switch ($Mode) {
    "standalone" { Run-Standalone }
    "docker" { Run-Docker }
}
