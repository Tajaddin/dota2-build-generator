"""The one HTTP client for the OpenDota API.

Every call goes through here so the app stays a polite API user:

- at most one request per ``min_interval`` seconds (default 1.0 s, i.e. 60 a minute, the free limit);
- reads ``X-Rate-Limit-Remaining-Minute`` and ``-Day`` and waits or stops before hitting them;
- backs off on 429 (honouring ``Retry-After``) and retries 5xx and network errors;
- caches every GET on disk with a per-call lifetime, so a rerun spends no requests on fresh data;
- counts requests per UTC day in ``usage.json`` for the Setup page.
"""

from __future__ import annotations

import hashlib
import json
import threading
import time
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

from d2bg import __version__, paths

BASE_URL = "https://api.opendota.com/api"
USER_AGENT = f"d2bg/{__version__} (+https://github.com/Tajaddin/dota2-build-generator)"

HOUR = 3600.0
DAY = 24 * HOUR


class OpenDotaError(RuntimeError):
    pass


class NotFoundError(OpenDotaError):
    pass


class BudgetExhaustedError(OpenDotaError):
    """The daily allowance left is below the reserve; try again tomorrow or add an API key."""


Params = Mapping[str, str | int | float | bool | list[str]]


class OpenDotaClient:
    def __init__(
        self,
        api_key: str | None = None,
        *,
        base_url: str = BASE_URL,
        cache_dir: Path | None = None,
        min_interval: float = 1.0,
        daily_reserve: int = 100,
        max_retries: int = 4,
        timeout: float = 30.0,
        transport: httpx.BaseTransport | None = None,
        clock: Callable[[], float] = time.monotonic,
        wall_clock: Callable[[], float] = time.time,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.cache_dir = cache_dir or paths.cache_dir() / "opendota"
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.min_interval = min_interval
        self.daily_reserve = daily_reserve
        self.max_retries = max_retries
        self._clock = clock
        self._wall = wall_clock
        self._sleep = sleep
        self._lock = threading.Lock()
        self._last_request: float | None = None
        self._http = httpx.Client(timeout=timeout, transport=transport, headers={"User-Agent": USER_AGENT})
        self.requests_made = 0
        self.cache_hits = 0
        self.remaining_minute: int | None = None
        self.remaining_day: int | None = None

    # ── cache ──────────────────────────────────────────────────────

    def _cache_key(self, method: str, path: str, params: Params | None) -> Path:
        items = sorted((k, str(v)) for k, v in (params or {}).items() if k != "api_key")
        raw = json.dumps([method, path, items])
        return self.cache_dir / f"{hashlib.sha256(raw.encode()).hexdigest()[:32]}.json"

    def _read_cache(self, file: Path, ttl: float | None) -> tuple[bool, Any]:
        if ttl is None or ttl <= 0 or not file.exists():
            return False, None
        try:
            doc = json.loads(file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return False, None
        if self._wall() - float(doc.get("fetched_at", 0)) > ttl:
            return False, None
        return True, doc.get("data")

    def _write_cache(self, file: Path, data: Any) -> None:
        tmp = file.with_suffix(".tmp")
        tmp.write_text(json.dumps({"fetched_at": self._wall(), "data": data}), encoding="utf-8")
        tmp.replace(file)

    # ── usage counter ──────────────────────────────────────────────

    def _usage_file(self) -> Path:
        return self.cache_dir / "usage.json"

    def usage(self) -> dict[str, Any]:
        today = datetime.fromtimestamp(self._wall(), tz=UTC).date().isoformat()
        try:
            doc = json.loads(self._usage_file().read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            doc = {}
        return {
            "date": today,
            "requests_today": int(doc.get(today, 0)),
            "remaining_minute": self.remaining_minute,
            "remaining_day": self.remaining_day,
            "has_api_key": bool(self.api_key),
        }

    def _count_request(self) -> None:
        today = datetime.fromtimestamp(self._wall(), tz=UTC).date().isoformat()
        try:
            doc = json.loads(self._usage_file().read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            doc = {}
        doc = {today: int(doc.get(today, 0)) + 1}
        self._usage_file().write_text(json.dumps(doc), encoding="utf-8")

    # ── requests ───────────────────────────────────────────────────

    def _pace(self) -> None:
        if self.remaining_day is not None and self.remaining_day <= self.daily_reserve:
            raise BudgetExhaustedError(
                f"OpenDota daily allowance nearly used ({self.remaining_day} left, "
                f"reserve {self.daily_reserve})"
            )
        if self._last_request is not None:
            wait = self.min_interval - (self._clock() - self._last_request)
            if wait > 0:
                self._sleep(wait)
        if self.remaining_minute is not None and self.remaining_minute <= 1:
            self._sleep(60.0)
            self.remaining_minute = None
        self._last_request = self._clock()

    def _read_limits(self, resp: httpx.Response) -> None:
        for header, attr in (
            ("X-Rate-Limit-Remaining-Minute", "remaining_minute"),
            ("X-Rate-Limit-Remaining-Day", "remaining_day"),
        ):
            value = resp.headers.get(header)
            if value is not None and value.lstrip("-").isdigit():
                setattr(self, attr, int(value))

    def _request(self, method: str, path: str, params: Params | None) -> Any:
        query: dict[str, str | int | float | bool | list[str]] = dict(params or {})
        if self.api_key:
            query["api_key"] = self.api_key
        url = f"{self.base_url}/{path.lstrip('/')}"
        last_error = "no attempt made"
        for attempt in range(self.max_retries):
            with self._lock:
                self._pace()
                self.requests_made += 1
                self._count_request()
            try:
                resp = self._http.request(method, url, params=query)
            except httpx.HTTPError as exc:
                last_error = f"network error: {exc}"
                self._sleep(2.0 * (attempt + 1))
                continue
            self._read_limits(resp)
            if resp.status_code == 429:
                retry_after = resp.headers.get("Retry-After", "")
                delay = float(retry_after) if retry_after.isdigit() else 30.0 * (attempt + 1)
                last_error = "429 Too Many Requests"
                self._sleep(delay)
                continue
            if resp.status_code >= 500:
                last_error = f"HTTP {resp.status_code}"
                self._sleep(5.0 * (attempt + 1))
                continue
            if resp.status_code == 404:
                raise NotFoundError(f"{method} {path}: not found")
            if resp.status_code >= 400:
                raise OpenDotaError(f"{method} {path}: HTTP {resp.status_code} {resp.text[:200]}")
            try:
                return resp.json()
            except json.JSONDecodeError as exc:
                raise OpenDotaError(f"{method} {path}: response is not JSON") from exc
        raise OpenDotaError(f"{method} {path}: gave up after {self.max_retries} attempts ({last_error})")

    def get(self, path: str, params: Params | None = None, *, ttl: float | None = DAY) -> Any:
        """GET with the disk cache. ``ttl=None`` or ``0`` always asks the API."""
        file = self._cache_key("GET", path, params)
        hit, data = self._read_cache(file, ttl)
        if hit:
            self.cache_hits += 1
            return data
        data = self._request("GET", path, params)
        self._write_cache(file, data)
        return data

    def cached(self, path: str, params: Params | None = None, *, max_age: float = 30 * DAY) -> Any | None:
        """A cached response if there is one, without touching the network."""
        hit, data = self._read_cache(self._cache_key("GET", path, params), max_age)
        return data if hit else None

    def post(self, path: str, params: Params | None = None) -> Any:
        return self._request("POST", path, params)

    def explorer(self, sql: str, *, ttl: float = DAY) -> list[dict[str, Any]]:
        doc = self.get("explorer", {"sql": sql}, ttl=ttl)
        if not isinstance(doc, dict):
            raise OpenDotaError("explorer: unexpected response")
        if doc.get("err"):
            raise OpenDotaError(f"explorer: {doc['err']}")
        rows = doc.get("rows")
        return rows if isinstance(rows, list) else []

    def close(self) -> None:
        self._http.close()
