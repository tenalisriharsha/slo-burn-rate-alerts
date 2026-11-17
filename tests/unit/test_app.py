"""Unit tests for sample-service/app.py's Flask routes and error-rate /
slow-rate / queue-depth state, using Flask's test client directly against
the real app module - no mocking of the project's own code. Covers the
documented behavior: GET / and /metrics, and GET/POST /error-rate,
/slow-rate, and /queue-depth including the clamping and validation
docs/README.md and the module's own docstring promise.
"""
import importlib
import sys
from pathlib import Path

import pytest

SAMPLE_SERVICE_DIR = Path(__file__).resolve().parents[2] / "sample-service"
sys.path.insert(0, str(SAMPLE_SERVICE_DIR))

app_module = importlib.import_module("app")


@pytest.fixture
def client():
    app_module.set_error_rate(0.001)
    app_module.set_slow_rate(0.001)
    app_module.set_queue_depth_target(5.0)
    return app_module.app.test_client()


def test_index_reports_service_name_and_current_state(client):
    response = client.get("/")
    assert response.status_code == 200
    body = response.get_json()
    assert body["service"] == "sample-service"
    assert body["error_rate"] == pytest.approx(0.001)
    assert body["slow_rate"] == pytest.approx(0.001)
    assert body["queue_depth_target"] == pytest.approx(5.0)
    assert body["traffic_rps"] == pytest.approx(app_module._traffic_rps)


def test_metrics_endpoint_exposes_prometheus_text_format(client):
    app_module.REQUEST_COUNTER.labels(method="GET", code="200").inc()
    response = client.get("/metrics")
    assert response.status_code == 200
    assert response.content_type.startswith("text/plain")
    body = response.get_data(as_text=True)
    assert "http_requests_total" in body
    assert 'code="200"' in body
    assert 'method="GET"' in body


def test_metrics_endpoint_exposes_the_latency_histogram_with_the_slo_bucket(client):
    """prometheus/latency_recording_rules.yml reads the cumulative
    le="0.3" bucket, so /metrics must expose it under that exact label -
    a missing or renamed bucket would silently zero out the latency SLO.
    """
    app_module.LATENCY_HISTOGRAM.observe(0.05)
    response = client.get("/metrics")
    body = response.get_data(as_text=True)
    assert "http_request_duration_seconds_bucket" in body
    assert 'le="0.3"' in body


def test_metrics_endpoint_exposes_the_queue_depth_gauge(client):
    """prometheus/saturation_recording_rules.yml reads
    sample_service_queue_depth directly, so /metrics must expose it under
    that exact metric name - a missing or renamed gauge would silently
    zero out the saturation SLO.
    """
    app_module.QUEUE_DEPTH_GAUGE.set(42.0)
    response = client.get("/metrics")
    body = response.get_data(as_text=True)
    assert "sample_service_queue_depth 42.0" in body


def test_get_error_rate_route_returns_current_rate(client):
    app_module.set_error_rate(0.25)
    response = client.get("/error-rate")
    assert response.status_code == 200
    assert response.get_json() == {"error_rate": 0.25}


def test_post_error_rate_sets_and_returns_the_new_rate(client):
    response = client.post("/error-rate", json={"rate": 0.5})
    assert response.status_code == 200
    assert response.get_json() == {"error_rate": 0.5}
    assert app_module.get_error_rate() == 0.5


@pytest.mark.parametrize(
    "requested,expected",
    [
        (1.5, 1.0),  # clamp above 1.0
        (-0.3, 0.0),  # clamp below 0.0
        (0.0, 0.0),
        (1.0, 1.0),
    ],
)
def test_post_error_rate_clamps_to_the_0_to_1_range(client, requested, expected):
    response = client.post("/error-rate", json={"rate": requested})
    assert response.status_code == 200
    assert response.get_json() == {"error_rate": expected}


def test_post_error_rate_without_rate_field_is_a_400():
    client = app_module.app.test_client()
    response = client.post("/error-rate", json={})
    assert response.status_code == 400
    assert "rate" in response.get_json()["error"]


def test_post_error_rate_with_non_numeric_rate_is_a_400():
    client = app_module.app.test_client()
    response = client.post("/error-rate", json={"rate": "not-a-number"})
    assert response.status_code == 400


def test_post_error_rate_with_no_body_is_a_400():
    client = app_module.app.test_client()
    response = client.post("/error-rate")
    assert response.status_code == 400


def test_set_error_rate_does_not_mutate_state_on_invalid_input(client):
    app_module.set_error_rate(0.2)
    client.post("/error-rate", json={"rate": "nope"})
    assert app_module.get_error_rate() == 0.2


def test_get_slow_rate_route_returns_current_rate(client):
    app_module.set_slow_rate(0.25)
    response = client.get("/slow-rate")
    assert response.status_code == 200
    assert response.get_json() == {"slow_rate": 0.25}


def test_post_slow_rate_sets_and_returns_the_new_rate(client):
    response = client.post("/slow-rate", json={"rate": 0.5})
    assert response.status_code == 200
    assert response.get_json() == {"slow_rate": 0.5}
    assert app_module.get_slow_rate() == 0.5


@pytest.mark.parametrize(
    "requested,expected",
    [
        (1.5, 1.0),  # clamp above 1.0
        (-0.3, 0.0),  # clamp below 0.0
        (0.0, 0.0),
        (1.0, 1.0),
    ],
)
def test_post_slow_rate_clamps_to_the_0_to_1_range(client, requested, expected):
    response = client.post("/slow-rate", json={"rate": requested})
    assert response.status_code == 200
    assert response.get_json() == {"slow_rate": expected}


def test_post_slow_rate_without_rate_field_is_a_400():
    client = app_module.app.test_client()
    response = client.post("/slow-rate", json={})
    assert response.status_code == 400
    assert "rate" in response.get_json()["error"]


def test_post_slow_rate_with_non_numeric_rate_is_a_400():
    client = app_module.app.test_client()
    response = client.post("/slow-rate", json={"rate": "not-a-number"})
    assert response.status_code == 400


def test_post_slow_rate_with_no_body_is_a_400():
    client = app_module.app.test_client()
    response = client.post("/slow-rate")
    assert response.status_code == 400


def test_set_slow_rate_does_not_mutate_state_on_invalid_input(client):
    app_module.set_slow_rate(0.2)
    client.post("/slow-rate", json={"rate": "nope"})
    assert app_module.get_slow_rate() == 0.2


def test_error_rate_and_slow_rate_are_independent_knobs(client):
    """app.py's docstring promises /error-rate and /slow-rate are
    independent controls - setting one must not perturb the other.
    """
    app_module.set_error_rate(0.4)
    app_module.set_slow_rate(0.1)
    client.post("/error-rate", json={"rate": 0.9})
    assert app_module.get_slow_rate() == 0.1
    client.post("/slow-rate", json={"rate": 0.9})
    assert app_module.get_error_rate() == 0.9


def test_get_queue_depth_route_returns_current_target(client):
    app_module.set_queue_depth_target(25.0)
    response = client.get("/queue-depth")
    assert response.status_code == 200
    assert response.get_json() == {"queue_depth_target": 25.0}


def test_post_queue_depth_sets_and_returns_the_new_target(client):
    response = client.post("/queue-depth", json={"target": 80})
    assert response.status_code == 200
    assert response.get_json() == {"queue_depth_target": 80.0}
    assert app_module.get_queue_depth_target() == 80.0


@pytest.mark.parametrize(
    "requested,expected",
    [
        (600, 500.0),  # clamp above 500.0 (README/docstring: 0-500 range)
        (-10, 0.0),  # clamp below 0.0
        (0, 0.0),
        (500, 500.0),
    ],
)
def test_post_queue_depth_clamps_to_the_0_to_500_range(client, requested, expected):
    response = client.post("/queue-depth", json={"target": requested})
    assert response.status_code == 200
    assert response.get_json() == {"queue_depth_target": expected}


def test_post_queue_depth_without_target_field_is_a_400():
    client = app_module.app.test_client()
    response = client.post("/queue-depth", json={})
    assert response.status_code == 400
    assert "target" in response.get_json()["error"]


def test_post_queue_depth_with_non_numeric_target_is_a_400():
    client = app_module.app.test_client()
    response = client.post("/queue-depth", json={"target": "not-a-number"})
    assert response.status_code == 400


def test_post_queue_depth_with_no_body_is_a_400():
    client = app_module.app.test_client()
    response = client.post("/queue-depth")
    assert response.status_code == 400


def test_set_queue_depth_does_not_mutate_state_on_invalid_input(client):
    app_module.set_queue_depth_target(30.0)
    client.post("/queue-depth", json={"target": "nope"})
    assert app_module.get_queue_depth_target() == 30.0


def test_queue_depth_is_independent_of_error_rate_and_slow_rate(client):
    """app.py's docstring promises /error-rate, /slow-rate, and
    /queue-depth are independent controls - setting one must not perturb
    the other two.
    """
    app_module.set_error_rate(0.4)
    app_module.set_slow_rate(0.1)
    app_module.set_queue_depth_target(10.0)
    client.post("/queue-depth", json={"target": 90})
    assert app_module.get_error_rate() == 0.4
    assert app_module.get_slow_rate() == 0.1
