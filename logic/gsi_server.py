"""HTTP server that receives Dota 2 Game State Integration data."""
import hmac
import json
import time
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from typing import Callable, Optional

MAX_BODY_BYTES = 1024 * 1024


class _GSIHandler(BaseHTTPRequestHandler):
    """Handler for GSI POST requests."""

    def do_POST(self):
        try:
            content_length = int(self.headers.get("Content-Length", 0))
        except ValueError:
            content_length = -1
        if not 0 <= content_length <= MAX_BODY_BYTES:
            self.send_response(413 if content_length > MAX_BODY_BYTES else 400)
            self.end_headers()
            return
        body = self.rfile.read(content_length)
        try:
            data = json.loads(body.decode("utf-8"))
            is_valid, reason = self.server.gsi_validate_auth(data)
            if not is_valid:
                print(f"[GSI] Rejected update: {reason}")
                self.send_response(403)
                self.end_headers()
                return
            self.server.gsi_callback(data)
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            print(f"[GSI] Failed to parse POST body: {e}")
        self.send_response(200)
        self.end_headers()

    def do_GET(self):
        """Health-check endpoint — visit http://127.0.0.1:4001 in a browser to verify."""
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.end_headers()
        status = (
            f"Dota 2 Build Generator - GSI Server\n"
            f"Status: running\n"
            f"Last update: {getattr(self.server, '_last_update_time', 'never')}\n"
            f"Updates received: {getattr(self.server, '_update_count', 0)}\n"
        )
        self.wfile.write(status.encode("utf-8"))

    def log_message(self, format, *args):
        """Suppress default HTTP logging."""
        pass


class GSIServer:
    """Receives Dota 2 Game State Integration data via HTTP POST.

    Usage:
        server = GSIServer(port=4001, on_update=my_callback, expected_auth_token=load_or_create_token())
        server.start()
        # ... server runs in background thread ...
        server.stop()
    """

    def __init__(
        self,
        port: int = 4001,
        on_update: Optional[Callable] = None,
        *,
        expected_auth_token: Optional[str],
    ):
        """``expected_auth_token`` is the token in the installed GSI config; None turns the check off."""
        self.port = port
        self.on_update = on_update
        self.expected_auth_token = expected_auth_token
        self._state: Optional[dict] = None
        self._server: Optional[HTTPServer] = None
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()
        self._update_count = 0
        self._last_update_time = None

    def _validate_auth(self, data: dict) -> tuple[bool, str]:
        if not self.expected_auth_token:
            return True, "auth disabled"

        auth = data.get("auth")
        if not isinstance(auth, dict):
            return False, "missing auth block"

        token = auth.get("token")
        if not isinstance(token, str) or not hmac.compare_digest(
            token.encode("utf-8"), self.expected_auth_token.encode("utf-8")
        ):
            return False, "invalid auth token"

        return True, "ok"

    def _handle_data(self, data: dict):
        self._update_count += 1
        self._last_update_time = time.strftime("%H:%M:%S")

        # Log first few updates and then periodically so you can confirm data is flowing
        if self._update_count <= 3 or self._update_count % 20 == 0:
            keys = list(data.keys())
            map_state = data.get("map", {}).get("game_state", "?")
            hero_name = data.get("hero", {}).get("name", "?")
            has_allplayers = "allplayers" in data
            has_draft = "draft" in data
            print(
                f"[GSI] Update #{self._update_count}: "
                f"keys={keys} state={map_state} hero={hero_name} "
                f"allplayers={has_allplayers} draft={has_draft}"
            )

        with self._lock:
            self._state = data
        if self.on_update:
            try:
                self.on_update(data)
            except Exception as e:
                print(f"[GSI] Callback error: {e}")
                import traceback
                traceback.print_exc()

    def start(self):
        """Start the GSI server in a background thread.

        Binds to 127.0.0.1 only: the installed GSI config posts there, and
        nothing on the network should be able to send game state.
        """
        self._server = HTTPServer(("127.0.0.1", self.port), _GSIHandler)
        self._server.gsi_callback = self._handle_data
        self._server.gsi_validate_auth = self._validate_auth
        self._server._update_count = 0
        self._server._last_update_time = "never"
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()
        print(f"[GSI] Server listening on http://127.0.0.1:{self.port}")
        print(f"[GSI] Verify it's running: open http://127.0.0.1:{self.port} in your browser")
        if self.expected_auth_token:
            print("[GSI] Auth validation enabled")
        else:
            print("[GSI] Auth validation disabled")

    def stop(self):
        """Stop the GSI server."""
        if self._server:
            self._server.shutdown()
            self._server = None
            self._thread = None
            print("[GSI] Server stopped")

    def is_running(self) -> bool:
        return self._server is not None

    def get_state(self) -> Optional[dict]:
        """Get the latest GSI state data."""
        with self._lock:
            return self._state

    @property
    def update_count(self) -> int:
        return self._update_count
