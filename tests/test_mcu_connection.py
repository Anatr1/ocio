"""A router socket alone is not evidence that the crosswalk sketch is running."""
import pytest

from crosswalk.config import load_config
from crosswalk import mcu as link


def test_explicit_hardware_mode_refuses_virtual_fallback(monkeypatch):
    cfg = load_config().mcu
    cfg.enabled = True
    monkeypatch.setattr(link.os.path, "exists", lambda _: False)
    with pytest.raises(RuntimeError, match="MCU.*socket"):
        link.MCU(cfg)


def test_connection_requires_crosswalk_rpc_and_closes_failed_client(monkeypatch):
    class WrongApp:
        def __init__(self, *args, **kwargs):
            self.handlers = {}
            self.closed = False

        def connect(self):
            pass

        def call(self, method):
            assert method == "ping"
            raise RuntimeError("method ping not available")

        def close(self):
            self.closed = True

    client = WrongApp()
    monkeypatch.setattr(link, "RouterClient", lambda *a, **kw: client)
    cfg = load_config().mcu
    cfg.enabled = False
    hardware = link.MCU(cfg)
    hardware._connect()
    assert not hardware.state["connected"]
    assert hardware.client is None
    assert "ping not available" in hardware.state["error"]
    assert client.closed


def test_connection_accepts_crosswalk_rpc_and_resends_commands(monkeypatch):
    class Sketch:
        def __init__(self, *args, **kwargs):
            self.handlers = {}

        def connect(self):
            pass

        def call(self, method):
            assert method == "ping"
            return 123

    monkeypatch.setattr(link, "RouterClient", Sketch)
    cfg = load_config().mcu
    cfg.enabled = False
    hardware = link.MCU(cfg)
    hardware._sent["set_signal"] = (3, 1)
    hardware._connect()
    assert hardware.state["connected"] and hardware.state["error"] is None
    assert not hardware._sent
