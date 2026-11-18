"""Validates the Prometheus/Alertmanager configs with the real tools, the
same way `make check` and tests/promtool/rules_test.yml document they
should pass. Runs promtool/amtool inside their official Docker images, so
no local install of either binary is required.
"""
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]

pytestmark = pytest.mark.skipif(
    shutil.which("docker") is None, reason="docker is required to run promtool/amtool"
)

PROMETHEUS_IMAGE = "prom/prometheus:latest"
ALERTMANAGER_IMAGE = "prom/alertmanager:latest"


def _run_promtool(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [
            "docker",
            "run",
            "--rm",
            "-v",
            f"{REPO_ROOT}:/work",
            "-w",
            "/work",
            "--entrypoint",
            "promtool",
            PROMETHEUS_IMAGE,
            *args,
        ],
        capture_output=True,
        text=True,
        timeout=90,
    )


def _run_amtool(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [
            "docker",
            "run",
            "--rm",
            "-v",
            f"{REPO_ROOT}:/work",
            "-w",
            "/work",
            "--entrypoint",
            "amtool",
            ALERTMANAGER_IMAGE,
            *args,
        ],
        capture_output=True,
        text=True,
        timeout=90,
    )


def test_promtool_check_config_passes():
    # prometheus.yml's rule_files entries are the absolute /etc/prometheus/...
    # paths docker-compose.yml mounts prometheus/ to, not paths relative to
    # the repo - so check config needs that same mount (as `make check` does),
    # not the repo-root mount the other tests in this file use.
    result = subprocess.run(
        [
            "docker",
            "run",
            "--rm",
            "-v",
            f"{REPO_ROOT / 'prometheus'}:/etc/prometheus:ro",
            "--entrypoint",
            "promtool",
            PROMETHEUS_IMAGE,
            "check",
            "config",
            "/etc/prometheus/prometheus.yml",
        ],
        capture_output=True,
        text=True,
        timeout=90,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_promtool_check_rules_passes():
    # Mirrors `make check-prometheus`, which validates all six rule files -
    # the availability and latency pairs plus the saturation pair added
    # alongside the third SLO - not just the first two SLOs.
    result = _run_promtool(
        "check",
        "rules",
        "prometheus/recording_rules.yml",
        "prometheus/alerting_rules.yml",
        "prometheus/latency_recording_rules.yml",
        "prometheus/latency_alerting_rules.yml",
        "prometheus/saturation_recording_rules.yml",
        "prometheus/saturation_alerting_rules.yml",
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_amtool_check_config_passes():
    result = _run_amtool("check-config", "alertmanager/alertmanager.yml")
    assert result.returncode == 0, result.stdout + result.stderr


def test_promtool_rule_unit_tests_pass():
    """The alert-tier boundary tests PROGRESS.md claims already exist.

    PROGRESS.md (phase 2) says tests/promtool/rules_test.yml already covers
    each alert tier's threshold boundaries, but no such file was present
    before this test suite was written, and tests/promtool/ was empty. This
    test runs the unit-test file (added alongside this test) through the
    real promtool binary so a future change to the rules that breaks a
    tier's boundary behavior fails here instead of only in production.
    """
    result = _run_promtool("test", "rules", "tests/promtool/rules_test.yml")
    assert result.returncode == 0, result.stdout + result.stderr


def test_promtool_saturation_rule_unit_tests_pass():
    """Phase 4's saturation SLO gets its own promtool unit-test file,
    tests/promtool/saturation_rules_test.yml, since its gauge-to-indicator
    recording rule (prometheus/saturation_recording_rules.yml) needs
    different input series than the counter-based availability/latency
    rules the other unit-test file exercises.
    """
    result = _run_promtool("test", "rules", "tests/promtool/saturation_rules_test.yml")
    assert result.returncode == 0, result.stdout + result.stderr


def test_promtool_saturation_rule_unit_tests_pass_repeatedly():
    """Regression test for the flaky cross-group race described in
    PROGRESS.md ("Also fixed: flaky test_promtool_saturation_rule_unit_tests_pass"):
    prometheus/saturation_recording_rules.yml used to split the
    indicator/ratio/burn-rate rules across three groups, which gave
    Prometheus no guarantee they'd evaluate in lockstep, so the fast
    tier's `for: 2m` boundary test failed roughly 20-30% of the time with
    no code change between runs. The fix (collapsing them into one group,
    PROGRESS.md) was verified by looping the same invocation 70 times with
    zero failures; this test loops a smaller but still statistically
    meaningful number of times so a reintroduction of the race - e.g. a
    future change that splits the rules back into separate groups - fails
    here instead of showing up as an intermittent CI failure days later.
    """
    failures = []
    for i in range(20):
        result = _run_promtool("test", "rules", "tests/promtool/saturation_rules_test.yml")
        if result.returncode != 0:
            failures.append((i, result.stdout + result.stderr))
    assert not failures, (
        f"{len(failures)}/20 runs failed (flaky race reintroduced): " + repr(failures[0])
    )
