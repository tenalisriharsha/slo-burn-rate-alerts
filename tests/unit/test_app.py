"""Unit tests for sample-service/app.py's Flask routes and error-rate
state, using Flask's test client directly against the real app module -
no mocking of the project's own code. Covers the documented behavior:
GET / and /metrics, and GET/POST /error-rate including the clamping and
validation docs/README.md and the module's own docstring promise.
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
    return app_module.app.test_client()


def test_index_reports_service_name_and_current_state(client):
    response = client.get("/")
    assert response.status_code == 200
    body = response.get_json()
    assert body["service"] == "sample-service"
    assert body["error_rate"] == pytest.approx(0.001)
    assert "traffic_rps" in body


def test_metrics_endpoint_exposes_prometheus_text_format(client):
    app_module.REQUEST_COUNTER.labels(method="GET", code="200").inc()
    response = client.get("/metrics")
    assert response.status_code == 200
    assert response.content_type.startswith("text/plain")
    body = response.get_data(as_text=True)
    assert "http_requests_total" in body
    assert 'code="200"' in body


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
