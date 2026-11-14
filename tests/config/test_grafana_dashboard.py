"""Structural checks on the Grafana dashboard and its provisioning,
against the 4 panels and auto-provisioning claims in PROGRESS.md phase 2
and README.md ("a provisioned dashboard ... no manual clicking").
"""
import json
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
DASHBOARD_FILE = REPO_ROOT / "grafana" / "dashboards" / "slo-burn-rate.json"
DATASOURCE_PROVISIONING = REPO_ROOT / "grafana" / "provisioning" / "datasources"
DASHBOARD_PROVISIONING = REPO_ROOT / "grafana" / "provisioning" / "dashboards"


def _load_dashboard() -> dict:
    return json.loads(DASHBOARD_FILE.read_text())


def test_dashboard_is_valid_json_with_the_documented_panels():
    dashboard = _load_dashboard()
    titles = {panel["title"] for panel in dashboard["panels"]}
    assert "Burn Rate by Window" in titles
    assert "Days Until Error Budget Exhausted" in titles
    assert "Request Rate vs Error Rate (5m)" in titles
    assert "Active SLO Alerts" in titles


def test_burn_rate_panel_covers_all_seven_windows():
    dashboard = _load_dashboard()
    panel = next(p for p in dashboard["panels"] if p["title"] == "Burn Rate by Window")
    exprs = {t["expr"] for t in panel["targets"]}
    for window in ["5m", "30m", "1h", "2h", "6h", "1d", "3d"]:
        assert f"sample_service:burnrate{window}" in exprs


def test_days_remaining_gauge_uses_the_1h_burn_rate():
    dashboard = _load_dashboard()
    panel = next(
        p for p in dashboard["panels"] if p["title"] == "Days Until Error Budget Exhausted"
    )
    expr = panel["targets"][0]["expr"]
    assert "sample_service:burnrate1h" in expr
    assert "30" in expr


def test_active_alerts_panel_filters_by_the_documented_slo_label():
    dashboard = _load_dashboard()
    panel = next(p for p in dashboard["panels"] if p["title"] == "Active SLO Alerts")
    expr = panel["targets"][0]["expr"]
    assert 'slo="sample-service-availability"' in expr


def test_all_panels_use_the_provisioned_prometheus_datasource():
    dashboard = _load_dashboard()
    for panel in dashboard["panels"]:
        assert panel["datasource"]["uid"] == "prometheus"


def test_dashboard_provider_points_at_the_dashboards_directory():
    config = yaml.safe_load((DASHBOARD_PROVISIONING / "dashboards.yml").read_text())
    provider = config["providers"][0]
    assert provider["options"]["path"] == "/var/lib/grafana/dashboards"


def test_datasource_provisioning_points_at_the_prometheus_service():
    config = yaml.safe_load((DATASOURCE_PROVISIONING / "prometheus.yml").read_text())
    datasource = config["datasources"][0]
    assert datasource["type"] == "prometheus"
    assert datasource["url"] == "http://prometheus:9090"
    assert datasource["uid"] == "prometheus"
