# r360-reasoning gate wrapper. The gate runs in a container; the host has no make,
# no protoc and no C++ toolchain. Agent and CI issue the identical command.
#
#   .\gate.ps1            run the full gate
#   .\gate.ps1 shell      interactive shell in the same image
#   .\gate.ps1 <target>   run one make target in the gate image

param([string]$Target = "gate")

$ErrorActionPreference = "Stop"

try { docker version --format '{{.Server.Version}}' | Out-Null }
catch { Write-Error "Docker is not running. Start Docker Desktop."; exit 1 }

switch ($Target) {
    "gate"  { docker compose run --rm gate }
    "shell" { docker compose run --rm shell }
    "build" { docker compose build }
    default { docker compose run --rm gate make $Target }
}
exit $LASTEXITCODE
