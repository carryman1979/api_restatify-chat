param(
    [ValidateSet("standalone", "docker", "all")]
    [string]$Mode = "standalone"
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

function Install-Standalone {
    Ensure-EnvFile

    if (-not (Test-Path ".venv")) {
        python -m venv .venv
    }

    & .\.venv\Scripts\python.exe -m pip install --upgrade pip
    & .\.venv\Scripts\python.exe -m pip install -e .

    Write-Host "Standalone installation complete."
}

function Install-Docker {
    Ensure-EnvFile

    docker compose build
    Write-Host "Docker image build complete."
}

switch ($Mode) {
    "standalone" { Install-Standalone }
    "docker" { Install-Docker }
    "all" {
        Install-Standalone
        Install-Docker
    }
}

Write-Host "Done. Use .\run.ps1 -Mode standalone|docker to start the API."
