"""Structural checks on prometheus/recording_rules.yml: the 7 documented
windows (5m, 30m, 1h, 2h, 6h, 1d, 3d) exist for requests, errors, error
ratio, and burn rate, and the burn-rate divisor matches the documented
0.1% error budget (README.md / docs/runbook.md: 99.9% availability SLO).
"""
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
RULES_FILE = REPO_ROOT / "prometheus" / "recording_rules.yml"

WINDOWS = ["5m", "30m", "1h", "2h", "6h", "1d", "3d"]


def _load_records() -> dict:
    data = yaml.safe_load(RULES_FILE.read_text())
    records = {}
    for group in data["groups"]:
        for rule in group["rules"]:
            if "record" in rule:
                records[rule["record"]] = rule["expr"]
    return records


def test_requests_and_errors_rate_exist_for_all_windows():
    records = _load_records()
    for window in WINDOWS:
        assert f"sample_service:requests:rate{window}" in records
        assert f"sample_service:errors:rate{window}" in records


def test_error_ratio_divides_errors_by_requests_for_all_windows():
    records = _load_records()
    for window in WINDOWS:
        expr = records[f"sample_service:error_ratio:rate{window}"]
        assert f"sample_service:errors:rate{window}" in expr
        assert f"sample_service:requests:rate{window}" in expr
        assert "/" in expr


def test_burnrate_divides_error_ratio_by_the_documented_error_budget():
    records = _load_records()
    for window in WINDOWS:
        expr = records[f"sample_service:burnrate{window}"]
        assert f"sample_service:error_ratio:rate{window}" in expr
        # README/runbook: SLO = 99.9% availability -> error budget = 0.001.
        assert "0.001" in expr


def test_requests_rate_sums_over_the_sample_service_job_only():
    records = _load_records()
    expr = records["sample_service:requests:rate5m"]
    assert 'job="sample-service"' in expr
    assert "sum(rate(" in expr


def test_errors_rate_filters_5xx_status_codes():
    records = _load_records()
    expr = records["sample_service:errors:rate5m"]
    assert 'job="sample-service"' in expr
    assert 'code=~"5..' in expr
