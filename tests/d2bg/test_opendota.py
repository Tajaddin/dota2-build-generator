"""The OpenDota client: pacing, limits, back-off, caching and the usage counter (all mocked)."""

from __future__ import annotations

import httpx
import pytest
import respx

from d2bg.opendota import BudgetExhaustedError, NotFoundError, OpenDotaClient, OpenDotaError

BASE = "https://api.opendota.com/api"


class FakeTime:
    def __init__(self) -> None:
        self.now = 1000.0
        self.slept: list[float] = []

    def clock(self) -> float:
        return self.now

    def sleep(self, s: float) -> None:
        self.slept.append(s)
        self.now += s


@pytest.fixture
def ft() -> FakeTime:
    return FakeTime()


@pytest.fixture
def client(tmp_path, ft) -> OpenDotaClient:
    return OpenDotaClient(
        cache_dir=tmp_path, min_interval=1.0, clock=ft.clock, wall_clock=ft.clock, sleep=ft.sleep
    )


@respx.mock
def test_get_caches_within_ttl(client):
    route = respx.get(f"{BASE}/heroStats").mock(return_value=httpx.Response(200, json=[{"id": 1}]))
    assert client.get("heroStats", ttl=60) == [{"id": 1}]
    assert client.get("heroStats", ttl=60) == [{"id": 1}]
    assert route.call_count == 1
    assert client.cache_hits == 1


@respx.mock
def test_ttl_zero_always_fetches(client):
    route = respx.get(f"{BASE}/live").mock(return_value=httpx.Response(200, json=[]))
    client.get("live", ttl=0)
    client.get("live", ttl=0)
    assert route.call_count == 2


@respx.mock
def test_expired_cache_refetches(client, ft):
    route = respx.get(f"{BASE}/heroStats").mock(return_value=httpx.Response(200, json=[]))
    client.get("heroStats", ttl=10)
    ft.now += 11
    client.get("heroStats", ttl=10)
    assert route.call_count == 2


@respx.mock
def test_requests_are_paced(client, ft):
    respx.get(f"{BASE}/a").mock(return_value=httpx.Response(200, json=1))
    respx.get(f"{BASE}/b").mock(return_value=httpx.Response(200, json=2))
    client.get("a", ttl=0)
    client.get("b", ttl=0)
    assert ft.slept == [pytest.approx(1.0)]


@respx.mock
def test_429_backs_off_with_retry_after(client, ft):
    route = respx.get(f"{BASE}/x").mock(
        side_effect=[
            httpx.Response(429, headers={"Retry-After": "7"}),
            httpx.Response(200, json={"ok": True}),
        ]
    )
    assert client.get("x", ttl=0) == {"ok": True}
    assert route.call_count == 2
    assert 7.0 in ft.slept


@respx.mock
def test_5xx_retries_then_gives_up(client):
    respx.get(f"{BASE}/x").mock(return_value=httpx.Response(503))
    with pytest.raises(OpenDotaError, match="gave up"):
        client.get("x", ttl=0)
    assert client.requests_made == client.max_retries


@respx.mock
def test_404_is_not_found(client):
    respx.get(f"{BASE}/matches/1").mock(return_value=httpx.Response(404, json={"error": "Not Found"}))
    with pytest.raises(NotFoundError):
        client.get("matches/1", ttl=0)


@respx.mock
def test_reads_limits_and_stops_before_daily_reserve(client):
    respx.get(f"{BASE}/x").mock(
        return_value=httpx.Response(
            200, json=1, headers={"X-Rate-Limit-Remaining-Minute": "50", "X-Rate-Limit-Remaining-Day": "40"}
        )
    )
    client.get("x", ttl=0)
    assert client.remaining_minute == 50
    assert client.remaining_day == 40
    with pytest.raises(BudgetExhaustedError):
        client.get("x", ttl=0)


@respx.mock
def test_waits_a_minute_when_minute_quota_is_spent(client, ft):
    respx.get(f"{BASE}/x").mock(
        return_value=httpx.Response(200, json=1, headers={"X-Rate-Limit-Remaining-Minute": "1"})
    )
    client.get("x", ttl=0)
    client.get("x", ttl=0)
    assert 60.0 in ft.slept


@respx.mock
def test_api_key_is_sent_but_not_part_of_the_cache_key(tmp_path, ft):
    route = respx.get(f"{BASE}/heroStats").mock(return_value=httpx.Response(200, json=[]))
    keyed = OpenDotaClient(
        api_key="secret",
        cache_dir=tmp_path,
        min_interval=0,
        clock=ft.clock,
        wall_clock=ft.clock,
        sleep=ft.sleep,
    )
    keyed.get("heroStats", ttl=60)
    assert route.calls[0].request.url.params["api_key"] == "secret"
    plain = OpenDotaClient(
        cache_dir=tmp_path, min_interval=0, clock=ft.clock, wall_clock=ft.clock, sleep=ft.sleep
    )
    assert plain.get("heroStats", ttl=60) == []  # served from the cache written by the keyed client
    assert route.call_count == 1
    assert all("secret" not in f.read_text() for f in tmp_path.glob("*.json"))


@respx.mock
def test_usage_counts_requests_per_day(client):
    respx.get(f"{BASE}/x").mock(return_value=httpx.Response(200, json=1))
    client.get("x", ttl=0)
    client.get("x", ttl=0)
    usage = client.usage()
    assert usage["requests_today"] == 2
    assert usage["has_api_key"] is False


@respx.mock
def test_explorer_returns_rows_and_raises_on_sql_error(client):
    respx.get(f"{BASE}/explorer").mock(
        side_effect=[
            httpx.Response(200, json={"rows": [{"a": 1}]}),
            httpx.Response(200, json={"err": "syntax error"}),
        ]
    )
    assert client.explorer("SELECT 1", ttl=0) == [{"a": 1}]
    with pytest.raises(OpenDotaError, match="syntax error"):
        client.explorer("SELECT", ttl=0)


@respx.mock
def test_list_params_repeat(client):
    route = respx.get(f"{BASE}/players/1/matches").mock(return_value=httpx.Response(200, json=[]))
    client.get("players/1/matches", {"project": ["hero_id", "kills"]}, ttl=0)
    assert route.calls[0].request.url.params.get_list("project") == ["hero_id", "kills"]


def test_cached_reads_without_network(client):
    assert client.cached("heroStats") is None
