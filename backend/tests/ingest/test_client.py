from datetime import date

import httpx
import pytest
import respx

from bioage.ingest.client import BASE_URL, GoogleHealthClient, GoogleHealthError
from bioage.ingest.registry import get_spec
from bioage.types import DateRange


def make_client(**kwargs) -> GoogleHealthClient:
    return GoogleHealthClient(token_provider=lambda: "test-token", sleep=lambda _: None, **kwargs)


def test_filter_expression_uses_the_specs_filter_field():
    spec = get_spec("daily-resting-heart-rate")
    window = DateRange(date(2026, 6, 1), date(2026, 6, 15))
    built = make_client().build_filter(spec, window)
    # Derived from the spec, not hard-coded: a literal here duplicates the registry and
    # silently goes stale when a filter field is corrected, which is how the camelCase
    # roots survived until Google rejected them at runtime.
    assert built.count(spec.filter_field) == 2
    assert '"2026-06-01"' in built
    assert '"2026-06-15"' in built
    assert " AND " in built


@respx.mock
def test_sends_the_bearer_token():
    route = respx.get(url__startswith=f"{BASE_URL}/users/me/dataTypes/").mock(
        return_value=httpx.Response(200, json={"dataPoints": []})
    )
    make_client().list_data_points(
        get_spec("daily-resting-heart-rate"), DateRange(date(2026, 6, 1), date(2026, 6, 10))
    )
    assert route.calls[0].request.headers["Authorization"] == "Bearer test-token"


@respx.mock
def test_follows_pagination_until_the_token_is_exhausted():
    responses = [
        httpx.Response(200, json={"dataPoints": [{"a": 1}], "nextPageToken": "p2"}),
        httpx.Response(200, json={"dataPoints": [{"a": 2}], "nextPageToken": "p3"}),
        httpx.Response(200, json={"dataPoints": [{"a": 3}]}),
    ]
    respx.get(url__startswith=BASE_URL).mock(side_effect=responses)
    points = make_client().list_data_points(
        get_spec("daily-resting-heart-rate"), DateRange(date(2026, 6, 1), date(2026, 6, 10))
    )
    assert len(points) == 3


@respx.mock
def test_an_empty_string_page_token_terminates_pagination():
    """An empty-string nextPageToken must be treated as absent, not looped on forever."""
    responses = [
        httpx.Response(200, json={"dataPoints": [{"a": 1}], "nextPageToken": "p2"}),
        httpx.Response(200, json={"dataPoints": [{"a": 2}], "nextPageToken": ""}),
    ]
    route = respx.get(url__startswith=BASE_URL).mock(side_effect=responses)
    points = make_client().list_data_points(
        get_spec("daily-resting-heart-rate"), DateRange(date(2026, 6, 1), date(2026, 6, 10))
    )
    assert len(points) == 2
    assert route.call_count == 2


@respx.mock
def test_a_never_ending_page_token_raises_instead_of_hanging():
    """A server that keeps returning a non-empty nextPageToken forever (e.g. echoing the
    same stale cursor) must not spin the client forever -- it must fail with a diagnosable
    error once the page budget is exhausted."""
    route = respx.get(url__startswith=BASE_URL).mock(
        return_value=httpx.Response(
            200, json={"dataPoints": [{"a": 1}], "nextPageToken": "same-token-always"}
        )
    )
    with pytest.raises(GoogleHealthError, match="daily-resting-heart-rate"):
        make_client(max_pages=3).list_data_points(
            get_spec("daily-resting-heart-rate"), DateRange(date(2026, 6, 1), date(2026, 6, 10))
        )
    assert route.call_count == 3


@respx.mock
def test_two_hundred_day_backfill_is_split_into_three_requests():
    """The query cap is 90 days, so a 200-day range needs three sequential calls."""
    route = respx.get(url__startswith=BASE_URL).mock(
        return_value=httpx.Response(200, json={"dataPoints": []})
    )
    make_client().list_data_points(
        get_spec("steps"), DateRange(date(2026, 1, 1), date(2026, 7, 20))
    )
    assert route.call_count == 3


@respx.mock
def test_ninety_day_rhr_backfill_is_a_single_request():
    route = respx.get(url__startswith=BASE_URL).mock(
        return_value=httpx.Response(200, json={"dataPoints": []})
    )
    make_client().list_data_points(
        get_spec("daily-resting-heart-rate"), DateRange(date(2026, 1, 1), date(2026, 3, 31))
    )
    assert route.call_count == 1


@respx.mock
def test_retries_after_a_429_and_then_succeeds():
    respx.get(url__startswith=BASE_URL).mock(side_effect=[
        httpx.Response(429, json={"error": {"message": "rate limited"}}),
        httpx.Response(200, json={"dataPoints": [{"ok": True}]}),
    ])
    points = make_client().list_data_points(
        get_spec("daily-resting-heart-rate"), DateRange(date(2026, 6, 1), date(2026, 6, 10))
    )
    assert len(points) == 1


@respx.mock
def test_retry_after_header_wins_over_exponential_backoff():
    respx.get(url__startswith=BASE_URL).mock(side_effect=[
        httpx.Response(429, headers={"Retry-After": "7"}),
        httpx.Response(200, json={"dataPoints": []}),
    ])
    sleeps: list[float] = []
    client = GoogleHealthClient(
        token_provider=lambda: "test-token", sleep=lambda seconds: sleeps.append(seconds)
    )
    client.list_data_points(
        get_spec("daily-resting-heart-rate"), DateRange(date(2026, 6, 1), date(2026, 6, 10))
    )
    assert sleeps == [7.0]


@respx.mock
def test_retries_a_500_then_succeeds():
    respx.get(url__startswith=BASE_URL).mock(side_effect=[
        httpx.Response(500),
        httpx.Response(200, json={"dataPoints": []}),
    ])
    assert make_client().list_data_points(
        get_spec("daily-resting-heart-rate"), DateRange(date(2026, 6, 1), date(2026, 6, 10))
    ) == []


@respx.mock
def test_gives_up_after_the_retry_budget():
    respx.get(url__startswith=BASE_URL).mock(return_value=httpx.Response(429))
    with pytest.raises(GoogleHealthError, match="429"):
        make_client(max_retries=2).list_data_points(
            get_spec("daily-resting-heart-rate"), DateRange(date(2026, 6, 1), date(2026, 6, 10))
        )


@respx.mock
def test_a_401_forces_a_refresh_and_retries_once():
    respx.get(url__startswith=BASE_URL).mock(side_effect=[
        httpx.Response(401, json={"error": {"message": "invalid credential"}}),
        httpx.Response(200, json={"dataPoints": [{"ok": True}]}),
    ])
    refreshed = []

    def force_refresh() -> str:
        refreshed.append(True)
        return "refreshed-token"

    client = make_client(force_refresh=force_refresh)
    points = client.list_data_points(
        get_spec("daily-resting-heart-rate"), DateRange(date(2026, 6, 1), date(2026, 6, 10))
    )
    assert len(points) == 1
    assert refreshed == [True]


@respx.mock
def test_a_401_without_force_refresh_configured_raises_immediately():
    """Callers that never wire up force_refresh (e.g. a bare client in a unit test)
    keep the old behaviour: 401 is not retryable, so it fails fast."""
    route = respx.get(url__startswith=BASE_URL).mock(
        return_value=httpx.Response(401, json={"error": {"message": "invalid credential"}})
    )
    with pytest.raises(GoogleHealthError, match="401"):
        make_client().list_data_points(
            get_spec("daily-resting-heart-rate"), DateRange(date(2026, 6, 1), date(2026, 6, 10))
        )
    assert route.call_count == 1


@respx.mock
def test_a_401_that_persists_after_the_forced_refresh_fails_without_looping():
    """A permanently revoked token must not be retried five times with backoff like a
    transient 5xx -- exactly one forced-refresh retry, then fail."""
    route = respx.get(url__startswith=BASE_URL).mock(return_value=httpx.Response(401))
    client = make_client(force_refresh=lambda: "still-bad-token")
    with pytest.raises(GoogleHealthError, match="401"):
        client.list_data_points(
            get_spec("daily-resting-heart-rate"), DateRange(date(2026, 6, 1), date(2026, 6, 10))
        )
    # The original request plus exactly one retry after the forced refresh -- not the
    # 5-attempt backoff budget used for RETRYABLE_STATUSES.
    assert route.call_count == 2


@respx.mock
def test_does_not_retry_a_403():
    """A missing scope is not transient; retrying wastes quota and hides the cause."""
    route = respx.get(url__startswith=BASE_URL).mock(
        return_value=httpx.Response(403, json={"error": {"message": "insufficient scope"}})
    )
    with pytest.raises(GoogleHealthError, match="403"):
        make_client().list_data_points(
            get_spec("daily-resting-heart-rate"), DateRange(date(2026, 6, 1), date(2026, 6, 10))
        )
    assert route.call_count == 1


@respx.mock
def test_requests_the_specs_page_size():
    route = respx.get(url__startswith=BASE_URL).mock(
        return_value=httpx.Response(200, json={"dataPoints": []})
    )
    make_client().list_data_points(
        get_spec("sleep"), DateRange(date(2026, 6, 1), date(2026, 6, 10))
    )
    assert route.calls[0].request.url.params["pageSize"] == "25"


@respx.mock
def test_url_targets_the_correct_host_and_path():
    route = respx.get(url__startswith=BASE_URL).mock(
        return_value=httpx.Response(200, json={"dataPoints": []})
    )
    make_client().list_data_points(
        get_spec("steps"), DateRange(date(2026, 6, 1), date(2026, 6, 10))
    )
    url = str(route.calls[0].request.url)
    assert url.startswith("https://health.googleapis.com/v4/users/me/dataTypes/steps/dataPoints")
