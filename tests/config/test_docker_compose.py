"""Structural checks on docker-compose.yml against the "Quick start"
section of README.md: 4 services, the documented ports, and the wiring
between them (Prometheus depends on sample-service + alertmanager so
scrape targets exist before it starts; Grafana depends on Prometheus so
its datasource is reachable).
"""
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
COMPOSE_FILE = REPO_ROOT / "docker-compose.yml"

EXPECTED_PORTS = {
    "sample-service": "8000:8000",
    "prometheus": "9090:9090",
    "alertmanager": "9093:9093",
    "grafana": "3000:3000",
}


def _load_services() -> dict:
    return yaml.safe_load(COMPOSE_FILE.read_text())["services"]


def test_all_four_documented_services_exist():
    assert set(_load_services().keys()) == set(EXPECTED_PORTS.keys())


def test_each_service_exposes_its_documented_port():
    services = _load_services()
    for name, port_mapping in EXPECTED_PORTS.items():
        assert port_mapping in services[name]["ports"]


def test_sample_service_defaults_to_the_documented_healthy_baseline():
    env = _load_services()["sample-service"]["environment"]
    # README: "make reset ... back to the healthy baseline (0.1% errors)".
    assert env["ERROR_RATE"] == "0.001"


def test_grafana_has_anonymous_viewer_access_enabled():
    env = _load_services()["grafana"]["environment"]
    assert env["GF_AUTH_ANONYMOUS_ENABLED"] == "true"
    assert env["GF_AUTH_ANONYMOUS_ORG_ROLE"] == "Viewer"


def test_prometheus_depends_on_its_scrape_targets():
    depends_on = _load_services()["prometheus"]["depends_on"]
    assert "sample-service" in depends_on
    assert "alertmanager" in depends_on


def test_grafana_depends_on_prometheus():
    assert "prometheus" in _load_services()["grafana"]["depends_on"]


def test_prometheus_and_alertmanager_mount_their_config_dirs_read_only():
    services = _load_services()
    assert "./prometheus:/etc/prometheus:ro" in services["prometheus"]["volumes"]
    assert "./alertmanager:/etc/alertmanager:ro" in services["alertmanager"]["volumes"]
