"""Tests for GSI server."""

import http.client
import json
import socket
import time
import urllib.error
import urllib.request

from logic import gsi_installer
from logic.gsi_server import MAX_BODY_BYTES, GSIServer

TOKEN = "test-token"


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


class TestGSIServer:
    def test_server_starts_and_stops(self):
        port = _free_port()
        server = GSIServer(port=port, expected_auth_token=TOKEN)
        server.start()
        try:
            assert server.is_running()
        finally:
            server.stop()
        assert not server.is_running()

    def test_server_receives_gsi_data(self):
        port = _free_port()
        server = GSIServer(port=port, expected_auth_token=TOKEN)
        server.start()
        try:
            test_data = json.dumps(
                {
                    "player": {"team_name": "radiant"},
                    "hero": {"name": "npc_dota_hero_drow_ranger", "id": 6},
                    "map": {"game_state": "DOTA_GAMERULES_STATE_HERO_SELECTION"},
                    "auth": {"token": TOKEN},
                }
            ).encode("utf-8")
            req = urllib.request.Request(
                f"http://127.0.0.1:{port}",
                data=test_data,
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=3):
                pass
            time.sleep(0.2)

            state = server.get_state()
            assert state is not None
            assert "hero" in state
        finally:
            server.stop()

    def test_callback_fires_on_data(self):
        received = []
        port = _free_port()
        server = GSIServer(port=port, on_update=lambda data: received.append(data), expected_auth_token=TOKEN)
        server.start()
        try:
            test_data = json.dumps(
                {
                    "hero": {"name": "npc_dota_hero_antimage"},
                    "auth": {"token": TOKEN},
                }
            ).encode("utf-8")
            req = urllib.request.Request(
                f"http://127.0.0.1:{port}",
                data=test_data,
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=3):
                pass
            time.sleep(0.2)
            assert len(received) == 1
        finally:
            server.stop()

    def test_server_rejects_missing_auth_when_validation_enabled(self):
        received = []
        port = _free_port()
        server = GSIServer(port=port, on_update=lambda data: received.append(data), expected_auth_token=TOKEN)
        server.start()
        try:
            test_data = json.dumps({"hero": {"name": "npc_dota_hero_antimage"}}).encode("utf-8")
            req = urllib.request.Request(
                f"http://127.0.0.1:{port}",
                data=test_data,
                headers={"Content-Type": "application/json"},
            )
            try:
                urllib.request.urlopen(req, timeout=3)
                assert False, "expected 403 for missing auth"
            except urllib.error.HTTPError as exc:
                assert exc.code == 403

            time.sleep(0.2)
            assert server.get_state() is None
            assert received == []
            assert server.update_count == 0
        finally:
            server.stop()

    def test_server_accepts_requests_when_auth_validation_disabled(self):
        port = _free_port()
        server = GSIServer(port=port, expected_auth_token=None)
        server.start()
        try:
            test_data = json.dumps({"hero": {"name": "npc_dota_hero_antimage"}}).encode("utf-8")
            req = urllib.request.Request(
                f"http://127.0.0.1:{port}",
                data=test_data,
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=3):
                pass

            time.sleep(0.2)
            state = server.get_state()
            assert state is not None
            assert state["hero"]["name"] == "npc_dota_hero_antimage"
        finally:
            server.stop()

    def test_server_listens_on_loopback_only(self):
        server = GSIServer(port=_free_port(), expected_auth_token=TOKEN)
        server.start()
        try:
            assert server._server.server_address[0] == "127.0.0.1"
        finally:
            server.stop()

    def test_server_refuses_oversized_or_invalid_bodies_without_reading_them(self):
        received = []
        port = _free_port()
        server = GSIServer(port=port, on_update=lambda data: received.append(data), expected_auth_token=TOKEN)
        server.start()
        try:
            for length, status in ((str(MAX_BODY_BYTES + 1), 413), ("-1", 400), ("lots", 400)):
                conn = http.client.HTTPConnection("127.0.0.1", port, timeout=3)
                try:
                    conn.putrequest("POST", "/")
                    conn.putheader("Content-Type", "application/json")
                    conn.putheader("Content-Length", length)
                    conn.endheaders()  # no body: the server must answer from the header alone
                    assert conn.getresponse().status == status
                finally:
                    conn.close()
            assert received == []
        finally:
            server.stop()


class TestGSIToken:
    def test_each_install_gets_its_own_token(self, tmp_path):
        first = gsi_installer.load_or_create_token(tmp_path / "a" / "gsi_token")
        assert gsi_installer.load_or_create_token(tmp_path / "a" / "gsi_token") == first
        assert gsi_installer.load_or_create_token(tmp_path / "b" / "gsi_token") != first
        assert first != "buildgen_auth" and len(first) >= 32

    def test_installed_config_carries_the_token_and_old_configs_are_outdated(self, tmp_path, monkeypatch):
        monkeypatch.setattr(gsi_installer, "TOKEN_FILE", tmp_path / "gsi_token")
        dota = tmp_path / "dota 2 beta"
        ok, _ = gsi_installer.install_gsi_config(dota)
        assert ok
        token = gsi_installer.load_or_create_token()
        cfg = dota / "game" / "dota" / "cfg" / "gamestate_integration" / gsi_installer.CONFIG_FILENAME
        assert f'"{token}"' in cfg.read_text(encoding="utf-8")
        assert not gsi_installer.is_gsi_outdated(dota)
        cfg.write_text(cfg.read_text(encoding="utf-8").replace(token, "buildgen_auth"), encoding="utf-8")
        assert gsi_installer.is_gsi_outdated(dota)
