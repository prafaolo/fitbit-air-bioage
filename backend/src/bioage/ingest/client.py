"""HTTP client for the Google Health API.

Responsibilities kept deliberately narrow: build a filter expression, chunk a date range
to the data type's documented cap, paginate, retry what is transient, and return raw
payloads. Parsing happens elsewhere.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

import httpx

from bioage.ingest.registry import DataTypeSpec
from bioage.types import DateRange

BASE_URL = "https://health.googleapis.com/v4"

RETRYABLE_STATUSES = frozenset({429, 500, 502, 503, 504})
DEFAULT_MAX_RETRIES = 5
DEFAULT_BACKOFF_SECONDS = 1.0
# A 90-day chunk of the densest registered data type (steps, one point per minute) is at
# most 90 * 1440 = 129,600 points; at the largest page_size in the registry (1440) that is
# 90 pages for a fully legitimate response. 500 gives >5x headroom above any real payload
# while still bounding a pathological server (e.g. one that echoes a stale or repeating
# nextPageToken forever) to a finite, diagnosable failure instead of an infinite loop.
DEFAULT_MAX_PAGES = 500


class GoogleHealthError(RuntimeError):
    """A request failed and is not worth retrying, or the retry budget was exhausted."""


class RateLimitedError(GoogleHealthError):
    """The API returned 429 on every attempt within the retry budget."""


class GoogleHealthClient:
    def __init__(
        self,
        token_provider: Callable[[], str],
        http: httpx.Client | None = None,
        max_retries: int = DEFAULT_MAX_RETRIES,
        backoff_seconds: float = DEFAULT_BACKOFF_SECONDS,
        sleep: Callable[[float], None] = time.sleep,
        max_pages: int = DEFAULT_MAX_PAGES,
    ) -> None:
        self._token_provider = token_provider
        self._http = http or httpx.Client(timeout=30.0)
        self._max_retries = max_retries
        self._backoff_seconds = backoff_seconds
        self._sleep = sleep
        self._max_pages = max_pages

    def build_filter(self, spec: DataTypeSpec, window: DateRange) -> str:
        """AIP-160 filter constraining the query to a half-open date interval."""
        field = spec.filter_field
        return f'{field} >= "{window.start.isoformat()}" AND {field} < "{window.end.isoformat()}"'

    def list_data_points(self, spec: DataTypeSpec, window: DateRange) -> list[dict[str, Any]]:
        """Fetch every data point in `window`, chunking and paginating as needed."""
        points: list[dict[str, Any]] = []
        for chunk in window.chunked(spec.max_window_days):
            points.extend(self._list_chunk(spec, chunk))
        return points

    def _list_chunk(self, spec: DataTypeSpec, window: DateRange) -> list[dict[str, Any]]:
        url = f"{BASE_URL}/users/me/dataTypes/{spec.data_type_id}/dataPoints"
        params: dict[str, str | int] = {
            "filter": self.build_filter(spec, window),
            "pageSize": spec.page_size,
        }
        collected: list[dict[str, Any]] = []

        for _page in range(self._max_pages):
            payload = self._get(url, params)
            collected.extend(payload.get("dataPoints") or [])
            token = payload.get("nextPageToken")
            if not token:
                return collected
            params = {**params, "pageToken": token}

        raise GoogleHealthError(
            f"Google Health API paginated past the {self._max_pages}-page budget for "
            f"{spec.data_type_id} over {window.start}..{window.end}"
        )

    def _get(self, url: str, params: dict[str, str | int]) -> dict[str, Any]:
        last_status: int | None = None

        for attempt in range(self._max_retries):
            response = self._http.get(
                url,
                params=params,
                headers={"Authorization": f"Bearer {self._token_provider()}"},
            )
            if response.status_code == 200:
                result: dict[str, Any] = response.json()
                return result

            last_status = response.status_code
            if response.status_code not in RETRYABLE_STATUSES:
                raise GoogleHealthError(
                    f"Google Health API returned {response.status_code}: {response.text[:300]}"
                )
            # Exponential backoff; Retry-After wins when the server supplies it.
            delay = self._backoff_seconds * (2**attempt)
            retry_after = response.headers.get("Retry-After")
            if retry_after and retry_after.isdigit():
                delay = float(retry_after)
            self._sleep(delay)

        if last_status == 429:
            raise RateLimitedError(
                f"Google Health API returned 429 after {self._max_retries} attempts"
            )
        raise GoogleHealthError(
            f"Google Health API returned {last_status} after {self._max_retries} attempts"
        )
