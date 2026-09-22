from skail import cli


def test_omp_link_and_unlink_are_registered_and_dispatch(monkeypatch):
    called = []
    class FakeAdapter:
        def detect(self):
            return True

        def patch(self, config, port=None):
            called.append("link")

        def revert(self):
            called.append("unlink")

    monkeypatch.setattr("skail.harnesses.OmpAdapter", FakeAdapter)
    monkeypatch.setattr(cli, "load_config", lambda: type("Config", (), {"port": 11434, "shims": []})())
    monkeypatch.setattr("skail.launcher.install_shims", lambda _: None)
    monkeypatch.setattr("skail.launcher.uninstall_shims", lambda _: None)
    monkeypatch.setattr("skail.launcher.ensure_path_entry", lambda: None)
    monkeypatch.setattr("skail.launcher.remove_path_entry", lambda: None)
    cli.main(["omp", "link"])
    cli.main(["omp", "unlink"])
    assert called == ["link", "unlink"]
