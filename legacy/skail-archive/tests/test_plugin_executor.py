"""Plugin executor removal tests — verifies legacy Python executor proof-path files are removed."""

import pytest


def test_legacy_executor_files_removed():
    with pytest.raises(ImportError):
        import skail.plugin.executor_loop  # noqa: F401

    with pytest.raises(ImportError):
        import skail.plugin.synthesis  # noqa: F401

    with pytest.raises(ImportError):
        import skail.plugin.tools  # noqa: F401
