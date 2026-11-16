"""End-to-end test of the actual headline workflow this repo exists for:
simulate an incident against the real docker-compose stack and watch the
fast-burn alert tier move from inactive to firing in Prometheus, then show
up correctly routed (severity=critical) in Alertmanager - exactly what
README.md's "Quick start" and PROGRESS.md phase 1 describe doing manually.

None of the project's own code is mocked: this runs the real sample-service
container, the real prometheus/alerting_rules.yml evaluated by a real
Prometheus, and a real Alertmanager. It is slow (the fast tier's `for: 2m`
plus the time for its 1h recording-rule window to clear the 14.4x
threshold - a few minutes total) and requires Docker, so it is skipped by
default (see tests/conftest.py). Run explicitly with:

    RUN_INTEGRATION=1 pytest tests/integration -m integration
"""
import shutil
import subprocess
import time
from pathlib import Path

import pytest
import requests

REPO_ROOT = Path(__file__).resolve().parents[2]
PROJECT_NAME = "slo-burn-test"
SAMPLE_SERVICE_URL = "http://localhost:8000"
PROMETHEUS_URL = "http://localhost:9090"
ALERTMANAGER_URL = "http://localhost:9093"
INCIDENT_ERROR_RATE = 0.9
FAST_ALERT_NAME = "SampleServiceErrorBudgetBurnFast"
INCIDENT_QUEUE_DEPTH_TARGET = 200
SATURATION_FAST_ALERT_NAME = "SampleServiceSaturationBudgetBurnFast"

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(shutil.which("docker") is None, reason="docker is required"),
]


def _compose(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["docker", "compose", "-p", PROJECT_NAME, *args],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=180,
    )


def _wait_until(predicate, timeout_seconds, interval_seconds=5, description=""):
    deadline = time.monotonic() + timeout_seconds
    last_error = None
    while time.monotonic() < deadline:
        try:
            if predicate():
                return
        except Exception as exc:  # noqa: BLE001 - surfaced in the final assertion
            last_error = exc
        time.sleep(interval_seconds)
    raise AssertionError(
        f"timed out after {timeout_seconds}s waiting for: {description} "
        f"(last error: {last_error})"
    )


@pytest.fixture
def stack():
    _compose("down", "-v", "--remove-orphans")
    up = _compose("up", "-d", "--build", "sample-service", "prometheus", "alertmanager")
    assert up.returncode == 0, up.stdout + up.stderr
    try:
        yield
    finally:
        down = _compose("down", "-v", "--remove-orphans")
        assert down.returncode == 0, down.stdout + down.stderr


def test_simulated_incident_fires_the_fast_tier_alert_and_routes_to_page(stack):
    _wait_until(
        lambda: requests.get(f"{SAMPLE_SERVICE_URL}/", timeout=5).status_code == 200,
        timeout_seconds=60,
        description="sample-service to respond on :8000",
    )
    _wait_until(
        lambda: requests.get(f"{PROMETHEUS_URL}/-/ready", timeout=5).status_code == 200,
        timeout_seconds=60,
        description="prometheus to become ready",
    )

    response = requests.post(
        f"{SAMPLE_SERVICE_URL}/error-rate", json={"rate": INCIDENT_ERROR_RATE}, timeout=5
    )
    assert response.status_code == 200
    assert response.json() == {"error_rate": INCIDENT_ERROR_RATE}

    def fast_alert_is_firing():
        alerts = requests.get(f"{PROMETHEUS_URL}/api/v1/alerts", timeout=5).json()["data"][
            "alerts"
        ]
        return any(
            alert["labels"].get("alertname") == FAST_ALERT_NAME and alert["state"] == "firing"
            for alert in alerts
        )

    _wait_until(
        fast_alert_is_firing,
        timeout_seconds=9 * 60,
        interval_seconds=10,
        description=f"{FAST_ALERT_NAME} to reach state=firing in Prometheus",
    )

    def fast_alert_routed_to_page_in_alertmanager():
        alerts = requests.get(f"{ALERTMANAGER_URL}/api/v2/alerts", timeout=5).json()
        return any(
            alert["labels"].get("alertname") == FAST_ALERT_NAME
            and alert["labels"].get("severity") == "critical"
            for alert in alerts
        )

    _wait_until(
        fast_alert_routed_to_page_in_alertmanager,
        timeout_seconds=60,
        interval_seconds=5,
        description=f"{FAST_ALERT_NAME} to show up in Alertmanager with severity=critical",
    )


def test_simulated_saturation_incident_fires_the_fast_tier_alert_and_routes_to_page(stack):
    """Phase 4's headline workflow: the saturation SLO is built on a gauge
    (sample_service_queue_depth) rather than a counter, via the
    gauge-to-indicator adaptation in
    prometheus/saturation_recording_rules.yml - this proves that adaptation
    actually produces a firing, correctly-routed alert against the real
    stack, not just a structurally-valid recording rule.
    """
    _wait_until(
        lambda: requests.get(f"{SAMPLE_SERVICE_URL}/", timeout=5).status_code == 200,
        timeout_seconds=60,
        description="sample-service to respond on :8000",
    )
    _wait_until(
        lambda: requests.get(f"{PROMETHEUS_URL}/-/ready", timeout=5).status_code == 200,
        timeout_seconds=60,
        description="prometheus to become ready",
    )

    response = requests.post(
        f"{SAMPLE_SERVICE_URL}/queue-depth",
        json={"target": INCIDENT_QUEUE_DEPTH_TARGET},
        timeout=5,
    )
    assert response.status_code == 200
    assert response.json() == {"queue_depth_target": float(INCIDENT_QUEUE_DEPTH_TARGET)}

    def fast_alert_is_firing():
        alerts = requests.get(f"{PROMETHEUS_URL}/api/v1/alerts", timeout=5).json()["data"][
            "alerts"
        ]
        return any(
            alert["labels"].get("alertname") == SATURATION_FAST_ALERT_NAME
            and alert["state"] == "firing"
            for alert in alerts
        )

    _wait_until(
        fast_alert_is_firing,
        timeout_seconds=9 * 60,
        interval_seconds=10,
        description=f"{SATURATION_FAST_ALERT_NAME} to reach state=firing in Prometheus",
    )

    def fast_alert_routed_to_page_in_alertmanager():
        alerts = requests.get(f"{ALERTMANAGER_URL}/api/v2/alerts", timeout=5).json()
        return any(
            alert["labels"].get("alertname") == SATURATION_FAST_ALERT_NAME
            and alert["labels"].get("severity") == "critical"
            for alert in alerts
        )

    _wait_until(
        fast_alert_routed_to_page_in_alertmanager,
        timeout_seconds=60,
        interval_seconds=5,
        description=(
            f"{SATURATION_FAST_ALERT_NAME} to show up in Alertmanager with severity=critical"
        ),
    )
