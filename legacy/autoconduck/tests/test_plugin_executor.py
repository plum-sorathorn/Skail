"""Plugin executor removal tests — verifies legacy Python executor proof-path files are removed."""

import pytest


def test_legacy_executor_files_removed():
    with pytest.raises(ImportError):
        import autoconduck.plugin.executor_loop  # noqa: F401

    with pytest.raises(ImportError):
        import autoconduck.plugin.synthesis  # noqa: F401

    with pytest.raises(ImportError):
        import autoconduck.plugin.tools  # noqa: F401
