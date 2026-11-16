"""Structural checks on prometheus/saturation_recording_rules.yml: the
gauge-to-indicator adaptation and the same 7 documented windows (5m, 30m,
1h, 2h, 6h, 1d, 3d) as the other two SLOs, with the burn-rate divisor
matching the documented 2% saturation error budget (README.md /
docs/runbook.md "Saturation SLO": queue depth under 50 items at least 98%
of the time).
"""
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
RULES_FILE = REPO_ROOT / "prometheus" / "saturation_recording_rules.yml"

WINDOWS = ["5m", "30m", "1h", "2h", "6h", "1d", "3d"]


def _load_records() -> dict:
    data = yaml.safe_load(RULES_FILE.read_text())
    records = {}
    for group in data["groups"]:
        for rule in group["rules"]:
            if "record" in rule:
                records[rule["record"]] = rule["expr"]
    return records


def test_queue_saturated_bool_indicator_exists_and_thresholds_at_50():
    records = _load_records()
    expr = records["sample_service:queue_saturated:bool"]
    assert "sample_service_queue_depth" in expr
    assert 'job="sample-service"' in expr
    assert "> bool 50" in expr


def test_saturation_ratio_exists_for_all_windows():
    records = _load_records()
    for window in WINDOWS:
        assert f"sample_service:saturation_ratio:rate{window}" in records


def test_saturation_ratio_averages_the_bool_indicator_over_its_window():
    """docs/runbook.md: unlike the error/latency ratios, this is
    avg_over_time() of the 1/0 indicator, not rate()/rate() - there is no
    requests-count metric for saturation to divide by.
    """
    records = _load_records()
    for window in WINDOWS:
        expr = records[f"sample_service:saturation_ratio:rate{window}"]
        assert "avg_over_time(" in expr
        assert f"sample_service:queue_saturated:bool[{window}]" in expr


def test_saturation_burnrate_divides_saturation_ratio_by_the_documented_error_budget():
    records = _load_records()
    for window in WINDOWS:
        expr = records[f"sample_service:saturation_burnrate{window}"]
        assert f"sample_service:saturation_ratio:rate{window}" in expr
        # README/runbook: 98% not-saturated SLO -> error budget = 0.02.
        assert "0.02" in expr


def test_saturation_burnrate_is_not_reusing_the_other_slos_error_budget():
    """A copy-paste of the availability/latency burn-rate line would divide
    by 0.001 or 0.01 instead of the saturation SLO's own 0.02 budget.
    """
    records = _load_records()
    for window in WINDOWS:
        expr = records[f"sample_service:saturation_burnrate{window}"]
        assert "0.001" not in expr
        assert "0.01" not in expr
