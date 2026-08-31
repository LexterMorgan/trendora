"""V1 forecast API adapter tests. No database, no live GitHub."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID

from fastapi.testclient import TestClient

from trendora.analytics.models import MetricObservation, SubjectKind
from trendora.analytics.repository import InMemoryAnalyticsRepository
from trendora.analytics.service import AnalyticsService
from trendora.api import create_app
from trendora.api.app import get_github_forecast_product
from trendora.diagnostics.models import CadenceClass
from trendora.forecasting.models import ForecastModel, ForecastPoint
from trendora.product import GitHubForecastProduct, GitHubForecastRequest, GitHubForecastResult
from trendora.reference import SOURCE_IDS

UTC = timezone.utc
REPO = UUID("88888888-8888-4888-8888-888888888801")
REPO_EXT = "m10fixture/repo"
T0 = datetime(2026, 9, 1, 9, 0, tzinfo=UTC)
DAY = timedelta(days=1)
WEEK = timedelta(days=7)
PATH = "/api/v1/forecasts/github"


def _obs(value: int, at: datetime, snapshot: int, *, metric: str = "stargazer_count") -> MetricObservation:
    return MetricObservation(
        snapshot_id=UUID(int=snapshot),
        source_code="github",
        source_id=SOURCE_IDS["github"],
        metric_name=metric,
        metric_value=value,
        observed_at=at,
        collected_at=at,
        subject_kind=SubjectKind.CONTENT_ITEM,
        content_item_id=REPO,
        content_external_id=REPO_EXT,
        content_type="repository",
    )


def _rows(*pairs: tuple[int, datetime], metric: str = "stargazer_count") -> tuple[MetricObservation, ...]:
    return tuple(_obs(value, at, i + 1, metric=metric) for i, (value, at) in enumerate(pairs))


def _regular_stars() -> tuple[MetricObservation, ...]:
    return _rows((10, T0), (12, T0 + DAY), (15, T0 + 2 * DAY), (20, T0 + 3 * DAY))


def _make_app(*observations: MetricObservation) -> tuple[TestClient, GitHubForecastProduct]:
    product = GitHubForecastProduct(AnalyticsService(InMemoryAnalyticsRepository(observations)))
    app = create_app()
    app.dependency_overrides[get_github_forecast_product] = lambda: product
    return TestClient(app), product


def _parse(dt_str: str) -> datetime:
    return datetime.fromisoformat(dt_str)


class _RecordingProduct:
    """Stub proving the API is a pure adapter over the M10 product."""

    def __init__(self, result: GitHubForecastResult) -> None:
        self._result = result
        self.calls: list[GitHubForecastRequest] = []

    def forecast(self, request: GitHubForecastRequest) -> GitHubForecastResult:
        self.calls.append(request)
        return self._result


def _stub_result() -> GitHubForecastResult:
    return GitHubForecastResult(
        source_code="github",
        metric_name="stargazer_count",
        content_item_id=REPO,
        content_external_id=REPO_EXT,
        model=ForecastModel.NAIVE,
        horizon=4,
        interval=timedelta(days=7),
        origin="trendora_forecast",
        points=tuple(ForecastPoint(at=T0 + WEEK * n, value=999.0) for n in range(1, 5)),
        observation_count=5,
        history_start=T0,
        history_end=T0 + 3 * DAY,
        latest_observed_at=T0 + 3 * DAY,
        cadence=CadenceClass.VARIABLE,
        irregular_cadence=True,
    )


def test_stargazer_forecast_succeeds() -> None:
    client, _ = _make_app(*_regular_stars())
    response = client.get(f"{PATH}/{REPO}", params={"metric": "stargazer_count"})
    assert response.status_code == 200
    body = response.json()
    assert body["source_code"] == "github"
    assert body["metric_name"] == "stargazer_count"
    assert body["content_item_id"] == str(REPO)
    assert body["content_external_id"] == REPO_EXT


def test_fork_forecast_succeeds() -> None:
    rows = _rows((1, T0), (2, T0 + DAY), (2, T0 + 2 * DAY), (3, T0 + 3 * DAY), metric="fork_count")
    client, _ = _make_app(*rows)
    response = client.get(f"{PATH}/{REPO}", params={"metric": "fork_count"})
    assert response.status_code == 200
    assert response.json()["metric_name"] == "fork_count"


def test_exactly_four_forecast_points() -> None:
    client, _ = _make_app(*_regular_stars())
    body = client.get(f"{PATH}/{REPO}", params={"metric": "stargazer_count"}).json()
    assert len(body["points"]) == 4
    assert body["horizon"] == 4


def test_interval_is_seven_days() -> None:
    client, _ = _make_app(*_regular_stars())
    body = client.get(f"{PATH}/{REPO}", params={"metric": "stargazer_count"}).json()
    assert body["interval_days"] == 7


def test_model_is_naive() -> None:
    client, _ = _make_app(*_regular_stars())
    body = client.get(f"{PATH}/{REPO}", params={"metric": "stargazer_count"}).json()
    assert body["model"] == "naive"


def test_values_come_from_m10_not_api_math() -> None:
    client, product = _make_app(*_regular_stars())
    body = client.get(f"{PATH}/{REPO}", params={"metric": "stargazer_count"}).json()
    expected = product.forecast(
        GitHubForecastRequest(content_item_id=REPO, metric_name="stargazer_count")
    )
    assert [point["value"] for point in body["points"]] == [p.value for p in expected.points]
    assert [point["value"] for point in body["points"]] == [20.0, 20.0, 20.0, 20.0]


def test_generated_timestamps_are_latest_plus_7_14_21_28_days() -> None:
    client, _ = _make_app(*_regular_stars())
    body = client.get(f"{PATH}/{REPO}", params={"metric": "stargazer_count"}).json()
    latest = T0 + 3 * DAY
    assert [_parse(point["at"]) for point in body["points"]] == [
        latest + WEEK,
        latest + 2 * WEEK,
        latest + 3 * WEEK,
        latest + 4 * WEEK,
    ]


def test_origin_is_trendora_forecast() -> None:
    client, _ = _make_app(*_regular_stars())
    body = client.get(f"{PATH}/{REPO}", params={"metric": "stargazer_count"}).json()
    assert body["origin"] == "trendora_forecast"


def test_history_fields_are_returned() -> None:
    client, _ = _make_app(*_regular_stars())
    body = client.get(f"{PATH}/{REPO}", params={"metric": "stargazer_count"}).json()
    assert body["observation_count"] == 4
    assert _parse(body["history_start"]) == T0
    assert _parse(body["history_end"]) == T0 + 3 * DAY
    assert _parse(body["latest_observed_at"]) == T0 + 3 * DAY


def test_cadence_fields_are_returned() -> None:
    client, _ = _make_app(*_regular_stars())
    body = client.get(f"{PATH}/{REPO}", params={"metric": "stargazer_count"}).json()
    assert body["cadence"] == "effectively_constant_cadence"
    assert body["irregular_cadence"] is False


def test_irregular_cadence_is_preserved_as_caveat_not_rejection() -> None:
    rows = _rows((10, T0), (12, T0 + DAY), (15, T0 + 5 * DAY), (20, T0 + 9 * DAY))
    client, _ = _make_app(*rows)
    response = client.get(f"{PATH}/{REPO}", params={"metric": "stargazer_count"})
    assert response.status_code == 200
    body = response.json()
    assert body["cadence"] == "variable_cadence"
    assert body["irregular_cadence"] is True
    assert len(body["points"]) == 4


def test_invalid_metric_returns_422_invalid_metric() -> None:
    client, _ = _make_app(*_regular_stars())
    response = client.get(f"{PATH}/{REPO}", params={"metric": "watcher_count"})
    assert response.status_code == 422
    body = response.json()
    assert body["error"]["code"] == "invalid_metric"
    assert isinstance(body["error"]["message"], str)


def test_missing_metric_returns_422_invalid_metric() -> None:
    client, _ = _make_app(*_regular_stars())
    response = client.get(f"{PATH}/{REPO}")
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_metric"


def test_malformed_content_item_id_returns_422_invalid_request() -> None:
    client, _ = _make_app(*_regular_stars())
    response = client.get(f"{PATH}/not-a-uuid", params={"metric": "stargazer_count"})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_request"


def test_insufficient_history_returns_422() -> None:
    rows = _rows((10, T0), (12, T0 + DAY), (15, T0 + 2 * DAY))
    client, _ = _make_app(*rows)
    response = client.get(f"{PATH}/{REPO}", params={"metric": "stargazer_count"})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "forecast_insufficient_history"


def test_empty_history_returns_422() -> None:
    client, _ = _make_app()
    response = client.get(f"{PATH}/{REPO}", params={"metric": "stargazer_count"})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "forecast_insufficient_history"


def test_error_envelope_shape() -> None:
    client, _ = _make_app()
    response = client.get(f"{PATH}/{REPO}", params={"metric": "nope"})
    body = response.json()
    assert set(body) == {"error"}
    assert set(body["error"]) == {"code", "message"}


def test_no_post_endpoint() -> None:
    client, _ = _make_app(*_regular_stars())
    response = client.post(f"{PATH}/{REPO}", params={"metric": "stargazer_count"})
    assert response.status_code == 405


def test_api_is_pure_adapter_over_m10() -> None:
    result = _stub_result()
    recording = _RecordingProduct(result)
    app = create_app()
    app.dependency_overrides[get_github_forecast_product] = lambda: recording
    client = TestClient(app)
    response = client.get(f"{PATH}/{REPO}", params={"metric": "stargazer_count"})

    assert response.status_code == 200
    body = response.json()
    assert body["origin"] == result.origin
    assert [point["value"] for point in body["points"]] == [p.value for p in result.points]
    assert [_parse(point["at"]) for point in body["points"]] == [p.at for p in result.points]
    assert body["cadence"] == "variable_cadence"
    assert body["irregular_cadence"] is True
    assert len(recording.calls) == 1
    call = recording.calls[0]
    assert call.content_item_id == REPO
    assert call.metric_name == "stargazer_count"
    assert call.source_code == "github"
    assert call.publisher_id is None
