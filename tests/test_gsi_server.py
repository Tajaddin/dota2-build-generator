"""Tests for GSI server."""

import json
import socket
import time
import urllib.error
import urllib.request

from logic.gsi_server import GSIServer
from logic.gsi_installer import GSI_AUTH_TOKEN


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


class TestGSIServer:
    def test_server_starts_and_stops(self):
        port = _free_port()
        server = GSIServer(port=port)
        server.start()
        try:
            assert server.is_running()
        finally:
            server.stop()
        assert not server.is_running()

    def test_server_receives_gsi_data(self):
        port = _free_port()
        server = GSIServer(port=port)
        server.start()
        try:
            test_data = json.dumps(
                {
                    "player": {"team_name": "radiant"},
                    "hero": {"name": "npc_dota_hero_drow_ranger", "id": 6},
                    "map": {"game_state": "DOTA_GAMERULES_STATE_HERO_SELECTION"},
                    "auth": {"token": GSI_AUTH_TOKEN},
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
        server = GSIServer(port=port, on_update=lambda data: received.append(data))
        server.start()
        try:
            test_data = json.dumps(
                {
                    "hero": {"name": "npc_dota_hero_antimage"},
                    "auth": {"token": GSI_AUTH_TOKEN},
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
        server = GSIServer(port=port, on_update=lambda data: received.append(data))
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
