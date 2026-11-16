"""Structural checks on the Grafana dashboard and its provisioning,
against the panels and auto-provisioning claims in PROGRESS.md phases 2-4
and README.md ("a provisioned dashboard ... no manual clicking"): the
original 4 availability panels, the 3 latency panels added in phase 3, and
the 3 saturation panels added in phase 4 (PROGRESS.md: "3 new panels -
saturation burn rate by window, queue depth vs the 50-item threshold, and
the live saturation alert table").
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


def test_dashboard_includes_the_latency_panels():
    dashboard = _load_dashboard()
    titles = {panel["title"] for panel in dashboard["panels"]}
    assert "Latency Burn Rate by Window" in titles
    assert "p99 Latency Estimate" in titles
    assert "Active Latency SLO Alerts" in titles


def test_dashboard_includes_the_saturation_panels():
    dashboard = _load_dashboard()
    titles = {panel["title"] for panel in dashboard["panels"]}
    assert "Saturation Burn Rate by Window" in titles
    assert "Queue Depth vs Saturation Threshold" in titles
    assert "Active Saturation SLO Alerts" in titles


def test_latency_burn_rate_panel_covers_all_seven_windows():
    dashboard = _load_dashboard()
    panel = next(p for p in dashboard["panels"] if p["title"] == "Latency Burn Rate by Window")
    exprs = {t["expr"] for t in panel["targets"]}
    for window in ["5m", "30m", "1h", "2h", "6h", "1d", "3d"]:
        assert f"sample_service:latency_burnrate{window}" in exprs


def test_saturation_burn_rate_panel_covers_all_seven_windows():
    dashboard = _load_dashboard()
    panel = next(p for p in dashboard["panels"] if p["title"] == "Saturation Burn Rate by Window")
    exprs = {t["expr"] for t in panel["targets"]}
    for window in ["5m", "30m", "1h", "2h", "6h", "1d", "3d"]:
        assert f"sample_service:saturation_burnrate{window}" in exprs


def test_queue_depth_panel_queries_the_raw_gauge():
    dashboard = _load_dashboard()
    panel = next(
        p for p in dashboard["panels"] if p["title"] == "Queue Depth vs Saturation Threshold"
    )
    expr = panel["targets"][0]["expr"]
    assert "sample_service_queue_depth" in expr
    assert 'job="sample-service"' in expr


def test_active_latency_alerts_panel_filters_by_the_documented_slo_label():
    dashboard = _load_dashboard()
    panel = next(p for p in dashboard["panels"] if p["title"] == "Active Latency SLO Alerts")
    expr = panel["targets"][0]["expr"]
    assert 'slo="sample-service-latency"' in expr


def test_active_saturation_alerts_panel_filters_by_the_documented_slo_label():
    dashboard = _load_dashboard()
    panel = next(p for p in dashboard["panels"] if p["title"] == "Active Saturation SLO Alerts")
    expr = panel["targets"][0]["expr"]
    assert 'slo="sample-service-saturation"' in expr


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
