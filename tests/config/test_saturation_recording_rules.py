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
PROMETHEUS_YML = REPO_ROOT / "prometheus" / "prometheus.yml"

WINDOWS = ["5m", "30m", "1h", "2h", "6h", "1d", "3d"]


def _load_data() -> dict:
    return yaml.safe_load(RULES_FILE.read_text())


def _load_records() -> dict:
    data = _load_data()
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


def test_indicator_ratio_and_burnrate_rules_all_live_in_one_group():
    """Regression test for the cross-group race fixed in
    prometheus/saturation_recording_rules.yml (see PROGRESS.md "Also fixed:
    flaky test_promtool_saturation_rule_unit_tests_pass"): the indicator,
    ratio, and burn-rate rules used to be split across three separate
    groups, each depending on the previous one's recorded series. Prometheus
    only guarantees sequential evaluation *within* a group, not between
    groups, so a downstream group could occasionally read a one-cycle-stale
    value and intermittently miss the fast tier's `for: 2m` continuity
    check. All of these rules must stay in the same group so that
    guarantee holds.
    """
    data = _load_data()
    assert len(data["groups"]) == 1, (
        "saturation recording rules must live in a single group so every "
        "rule is guaranteed to see the current cycle's upstream values"
    )
    group = data["groups"][0]
    record_names = [rule["record"] for rule in group["rules"] if "record" in rule]
    assert record_names.count("sample_service:queue_saturated:bool") == 1
    indicator_index = record_names.index("sample_service:queue_saturated:bool")
    for window in WINDOWS:
        ratio_name = f"sample_service:saturation_ratio:rate{window}"
        burnrate_name = f"sample_service:saturation_burnrate{window}"
        assert record_names.index(ratio_name) > indicator_index
        assert record_names.index(burnrate_name) > record_names.index(ratio_name)


def test_saturation_group_interval_pinned_to_15s_matching_scrape_interval():
    """docs/runbook.md "Saturation SLO": the gauge-derived indicator is
    only as fine-grained as the evaluation_interval (documented as 15s),
    so this group's `interval:` must match prometheus.yml's real
    scrape_interval/evaluation_interval rather than drifting from it.
    """
    group = _load_data()["groups"][0]
    assert group["interval"] == "15s"
    prometheus_config = yaml.safe_load(PROMETHEUS_YML.read_text())
    assert prometheus_config["global"]["scrape_interval"] == "15s"
    assert prometheus_config["global"]["evaluation_interval"] == "15s"
