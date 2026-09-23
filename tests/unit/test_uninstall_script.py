from pathlib import Path


def test_uninstall_script_purges_only_canonical_or_explicit_state_roots() -> None:
    script = (
        Path(__file__).resolve().parents[2] / "scripts" / "uninstall_skail.ps1"
    ).read_text(encoding="utf-8")

    assert '[Environment]::GetFolderPath("UserProfile")' in script
    assert 'Join-Path $userProfilePath ".skail"' in script
    assert "$LegacyWorkspaceRoots" in script
    assert "Get-ChildItem" not in script
    assert "keyring.delete_password" in script
    assert "python -m pip uninstall -y skail-harness" in script
