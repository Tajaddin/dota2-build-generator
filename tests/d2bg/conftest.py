"""Shared fixtures. Tests run against the committed data snapshot and a throwaway user folder; none of
them touches the network (OpenDota calls are mocked with respx or a fake client)."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

# Isolate the user folder before anything imports d2bg.paths users.
_HOME = Path(tempfile.mkdtemp(prefix="d2bg-test-home-"))
os.environ["D2BG_HOME"] = str(_HOME)

from d2bg.context import AppContext  # noqa: E402
from d2bg.datastore import DataStore  # noqa: E402
from d2bg.opendota import OpenDotaClient  # noqa: E402
from d2bg.settings import SettingsStore  # noqa: E402


class NoNetworkClient(OpenDotaClient):
    def _request(self, method, path, params):  # type: ignore[no-untyped-def]
        raise AssertionError(f"test tried to reach OpenDota: {method} {path}")


@pytest.fixture(scope="session")
def data() -> DataStore:
    empty = _HOME / "no-refreshed-data"
    empty.mkdir(exist_ok=True)
    return DataStore(refreshed=empty)


@pytest.fixture
def ctx(data: DataStore, tmp_path: Path) -> AppContext:
    return AppContext(
        data=data,
        settings=SettingsStore(tmp_path / "settings.json"),
        client=NoNetworkClient(cache_dir=tmp_path / "cache", min_interval=0, sleep=lambda s: None),
    )


@pytest.fixture(scope="session")
def shared_ctx(data: DataStore) -> AppContext:
    tmp = Path(tempfile.mkdtemp(prefix="d2bg-shared-"))
    return AppContext(
        data=data,
        settings=SettingsStore(tmp / "settings.json"),
        client=NoNetworkClient(cache_dir=tmp / "cache", min_interval=0, sleep=lambda s: None),
    )
