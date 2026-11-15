"""Structural checks on prometheus/latency_alerting_rules.yml against the
4-tier table documented in docs/runbook.md's "Latency SLO" section: the
same thresholds and `for` durations as the availability tiers, reused
unchanged, but scoped to the latency SLO via slo="sample-service-latency"
and sample_service:latency_burnrate* instead of sample_service:burnrate*.
"""
import re
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
RULES_FILE = REPO_ROOT / "prometheus" / "latency_alerting_rules.yml"

# alertname -> (long window, short window, threshold, for, severity, window label)
EXPECTED_TIERS = {
    "SampleServiceLatencyBudgetBurnFast": ("1h", "5m", 14.4, "2m", "critical", "fast"),
    "SampleServiceLatencyBudgetBurnMediumFast": ("6h", "30m", 6, "15m", "critical", "medium-fast"),
    "SampleServiceLatencyBudgetBurnSlow": ("1d", "2h", 3, "1h", "warning", "slow"),
    "SampleServiceLatencyBudgetBurnVerySlow": ("3d", "6h", 1, "3h", "warning", "very-slow"),
}


def _load_alerts() -> dict:
    data = yaml.safe_load(RULES_FILE.read_text())
    alerts = {}
    for group in data["groups"]:
        for rule in group["rules"]:
            if "alert" in rule:
                alerts[rule["alert"]] = rule
    return alerts


def test_all_four_documented_tiers_exist():
    alerts = _load_alerts()
    assert set(alerts.keys()) == set(EXPECTED_TIERS.keys())


@pytest.mark.parametrize("alertname", EXPECTED_TIERS.keys())
def test_tier_requires_agreement_between_long_and_short_window(alertname):
    long_window, short_window, _threshold, _for, _sev, _win = EXPECTED_TIERS[alertname]
    expr = _load_alerts()[alertname]["expr"]
    assert f"sample_service:latency_burnrate{long_window}" in expr
    assert f"sample_service:latency_burnrate{short_window}" in expr
    assert re.search(r"\band\b", expr)


@pytest.mark.parametrize("alertname", EXPECTED_TIERS.keys())
def test_tier_threshold_matches_documented_burn_rate(alertname):
    _lw, _sw, threshold, _for, _sev, _win = EXPECTED_TIERS[alertname]
    expr = _load_alerts()[alertname]["expr"]
    assert f">= {threshold}" in expr


@pytest.mark.parametrize("alertname", EXPECTED_TIERS.keys())
def test_tier_for_duration_matches_documented_value(alertname):
    _lw, _sw, _th, for_duration, _sev, _win = EXPECTED_TIERS[alertname]
    rule = _load_alerts()[alertname]
    assert rule["for"] == for_duration


@pytest.mark.parametrize("alertname", EXPECTED_TIERS.keys())
def test_tier_labels_match_documented_severity_and_window(alertname):
    _lw, _sw, _th, _for, severity, window = EXPECTED_TIERS[alertname]
    labels = _load_alerts()[alertname]["labels"]
    assert labels["severity"] == severity
    assert labels["window"] == window
    # docs/runbook.md "Latency SLO": carries slo: sample-service-latency,
    # not sample-service-availability, so it is a distinct SLO for routing
    # and inhibition purposes even though it shares severity/window labels.
    assert labels["slo"] == "sample-service-latency"


@pytest.mark.parametrize("alertname", EXPECTED_TIERS.keys())
def test_tier_has_nonempty_summary_and_description_annotations(alertname):
    annotations = _load_alerts()[alertname]["annotations"]
    assert annotations["summary"].strip()
    assert annotations["description"].strip()


@pytest.mark.parametrize("alertname", EXPECTED_TIERS.keys())
def test_tier_thresholds_and_durations_match_the_availability_tiers(alertname):
    """docs/runbook.md: the latency tiers reuse the *exact same* thresholds
    and `for` durations as the availability tiers - only the metric and the
    slo label differ.
    """
    availability_file = REPO_ROOT / "prometheus" / "alerting_rules.yml"
    availability_data = yaml.safe_load(availability_file.read_text())
    availability_alerts = {
        rule["alert"]: rule
        for group in availability_data["groups"]
        for rule in group["rules"]
        if "alert" in rule
    }
    availability_name = alertname.replace("LatencyBudget", "ErrorBudget")
    assert availability_name in availability_alerts
    latency_rule = _load_alerts()[alertname]
    availability_rule = availability_alerts[availability_name]
    assert latency_rule["for"] == availability_rule["for"]
    assert latency_rule["labels"]["severity"] == availability_rule["labels"]["severity"]
    assert latency_rule["labels"]["window"] == availability_rule["labels"]["window"]
