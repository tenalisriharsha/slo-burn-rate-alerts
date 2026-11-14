"""Structural checks on prometheus/alerting_rules.yml against the 4-tier
table documented in README.md and docs/runbook.md.
"""
import re
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
RULES_FILE = REPO_ROOT / "prometheus" / "alerting_rules.yml"

# alertname -> (long window, short window, threshold, for, severity, window label)
EXPECTED_TIERS = {
    "SampleServiceErrorBudgetBurnFast": ("1h", "5m", 14.4, "2m", "critical", "fast"),
    "SampleServiceErrorBudgetBurnMediumFast": ("6h", "30m", 6, "15m", "critical", "medium-fast"),
    "SampleServiceErrorBudgetBurnSlow": ("1d", "2h", 3, "1h", "warning", "slow"),
    "SampleServiceErrorBudgetBurnVerySlow": ("3d", "6h", 1, "3h", "warning", "very-slow"),
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
    long_window, short_window, threshold, _for, _sev, _win = EXPECTED_TIERS[alertname]
    expr = _load_alerts()[alertname]["expr"]
    assert f"sample_service:burnrate{long_window}" in expr
    assert f"sample_service:burnrate{short_window}" in expr
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
    assert labels["slo"] == "sample-service-availability"


@pytest.mark.parametrize("alertname", EXPECTED_TIERS.keys())
def test_tier_has_nonempty_summary_and_description_annotations(alertname):
    annotations = _load_alerts()[alertname]["annotations"]
    assert annotations["summary"].strip()
    assert annotations["description"].strip()
