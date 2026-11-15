"""Structural checks on prometheus/latency_recording_rules.yml: the 7
documented windows (5m, 30m, 1h, 2h, 6h, 1d, 3d) exist for the fast-request
count, the latency ratio, and the latency burn rate, and the burn-rate
divisor matches the documented 1% latency error budget (README.md /
docs/runbook.md "Latency SLO": 99% of requests under 300ms).
"""
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
RULES_FILE = REPO_ROOT / "prometheus" / "latency_recording_rules.yml"

WINDOWS = ["5m", "30m", "1h", "2h", "6h", "1d", "3d"]


def _load_records() -> dict:
    data = yaml.safe_load(RULES_FILE.read_text())
    records = {}
    for group in data["groups"]:
        for rule in group["rules"]:
            if "record" in rule:
                records[rule["record"]] = rule["expr"]
    return records


def test_requests_fast_exists_for_all_windows():
    records = _load_records()
    for window in WINDOWS:
        assert f"sample_service:requests_fast:rate{window}" in records


def test_latency_ratio_is_the_complement_of_fast_over_total_for_all_windows():
    records = _load_records()
    for window in WINDOWS:
        expr = records[f"sample_service:latency_ratio:rate{window}"]
        assert f"sample_service:requests_fast:rate{window}" in expr
        assert f"sample_service:requests:rate{window}" in expr
        assert "1 -" in expr
        assert "/" in expr


def test_latency_burnrate_divides_latency_ratio_by_the_documented_error_budget():
    records = _load_records()
    for window in WINDOWS:
        expr = records[f"sample_service:latency_burnrate{window}"]
        assert f"sample_service:latency_ratio:rate{window}" in expr
        # README/runbook: SLO = 99% of requests under 300ms -> error budget = 0.01.
        assert "0.01" in expr


def test_requests_fast_sums_the_le_300ms_cumulative_bucket():
    records = _load_records()
    expr = records["sample_service:requests_fast:rate5m"]
    assert 'job="sample-service"' in expr
    assert 'le="0.3"' in expr
    assert "sum(rate(" in expr
    assert "http_request_duration_seconds_bucket" in expr


def test_latency_ratio_reuses_the_shared_total_requests_metric():
    """docs/runbook.md: latency_ratio reuses `sample_service:requests:rate<window>`
    from the availability recording rules rather than redefining its own
    request-count metric, so both SLOs agree on total traffic.
    """
    records = _load_records()
    for window in WINDOWS:
        expr = records[f"sample_service:latency_ratio:rate{window}"]
        assert "http_requests_total" not in expr
