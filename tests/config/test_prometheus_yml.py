"""Structural checks on prometheus/prometheus.yml: all six rule files
(availability + latency + saturation) are loaded and the sample service is
scraped, as required for recording_rules.yml / alerting_rules.yml / the
latency and saturation equivalents to ever evaluate against real data
(README.md "How it works" diagram, docs/runbook.md "Latency SLO" /
"Saturation SLO").
"""
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
CONFIG_FILE = REPO_ROOT / "prometheus" / "prometheus.yml"


def _load():
    return yaml.safe_load(CONFIG_FILE.read_text())


def test_both_rule_files_are_loaded():
    rule_files = _load()["rule_files"]
    assert any("recording_rules.yml" in f for f in rule_files)
    assert any("alerting_rules.yml" in f for f in rule_files)


def test_latency_rule_files_are_also_loaded():
    rule_files = _load()["rule_files"]
    assert any(f.endswith("latency_recording_rules.yml") for f in rule_files)
    assert any(f.endswith("latency_alerting_rules.yml") for f in rule_files)


def test_saturation_rule_files_are_also_loaded():
    rule_files = _load()["rule_files"]
    assert any(f.endswith("saturation_recording_rules.yml") for f in rule_files)
    assert any(f.endswith("saturation_alerting_rules.yml") for f in rule_files)


def test_scrapes_the_sample_service_on_its_documented_port():
    scrape_configs = _load()["scrape_configs"]
    jobs = {job["job_name"]: job for job in scrape_configs}
    assert "sample-service" in jobs
    targets = jobs["sample-service"]["static_configs"][0]["targets"]
    assert "sample-service:8000" in targets


def test_alerts_are_sent_to_the_alertmanager_service():
    alertmanagers = _load()["alerting"]["alertmanagers"]
    targets = alertmanagers[0]["static_configs"][0]["targets"]
    assert "alertmanager:9093" in targets
