[CmdletBinding(SupportsShouldProcess = $true, ConfirmImpact = "High")]
param(
    [string[]] $LegacyWorkspaceRoots = @(),
    [switch] $Yes
)

$ErrorActionPreference = "Stop"
$userProfilePath = [Environment]::GetFolderPath("UserProfile")
$globalStatePath = [IO.Path]::GetFullPath((Join-Path $userProfilePath ".skail"))
$expectedParent = [IO.Path]::GetFullPath($userProfilePath).TrimEnd("\")

if ((Split-Path -Leaf $globalStatePath) -ne ".skail" -or
    (Split-Path -Parent $globalStatePath).TrimEnd("\") -ne $expectedParent) {
    throw "Refusing to purge an unexpected global state path: $globalStatePath"
}

if (-not $Yes) {
    $answer = Read-Host "Remove Skail, OS-stored credentials, and $globalStatePath? [y/N]"
    if ($answer -notin @("y", "Y", "yes", "YES")) {
        Write-Output "Skail uninstall cancelled."
        exit 0
    }
}

$env:SKAIL_PURGE_ROOT = $globalStatePath
@'
import os
import tomllib
from pathlib import Path

try:
    import keyring
    from keyring.errors import PasswordDeleteError
except ImportError:
    raise SystemExit(0)

root = Path(os.environ["SKAIL_PURGE_ROOT"])
references = {
    ("llmgateway", "LLMGATEWAY_API_KEY"),
    ("openai", "OPENAI_API_KEY"),
    ("anthropic", "ANTHROPIC_API_KEY"),
}
config = root / "config.toml"
if config.is_file():
    try:
        providers = tomllib.loads(config.read_text(encoding="utf-8")).get("providers", {})
        for provider, settings in providers.items():
            if isinstance(settings, dict) and isinstance(settings.get("api_key_env"), str):
                references.add((provider, settings["api_key_env"]))
    except (OSError, tomllib.TOMLDecodeError):
        pass

for provider, reference in references:
    try:
        keyring.delete_password("skail-harness", f"{provider}:{reference}")
    except PasswordDeleteError:
        pass
'@ | python -
Remove-Item Env:SKAIL_PURGE_ROOT -ErrorAction SilentlyContinue

if (Test-Path -LiteralPath $globalStatePath) {
    Remove-Item -LiteralPath $globalStatePath -Recurse -Force
}

foreach ($workspaceRoot in $LegacyWorkspaceRoots) {
    $resolvedWorkspace = [IO.Path]::GetFullPath($workspaceRoot)
    $legacyPath = [IO.Path]::GetFullPath((Join-Path $resolvedWorkspace ".skail"))
    if ((Split-Path -Leaf $legacyPath) -ne ".skail" -or
        (Split-Path -Parent $legacyPath).TrimEnd("\") -ne $resolvedWorkspace.TrimEnd("\")) {
        throw "Refusing to purge an unexpected legacy path: $legacyPath"
    }
    if (Test-Path -LiteralPath $legacyPath) {
        Remove-Item -LiteralPath $legacyPath -Recurse -Force
    }
}

if (Get-Command pipx -ErrorAction SilentlyContinue) {
    pipx uninstall skail-harness 2>$null
}
python -m pip uninstall -y skail-harness

Write-Output "Skail installation, global state, and registered credentials were removed."
