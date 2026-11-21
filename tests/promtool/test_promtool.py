"""Validates the Prometheus/Alertmanager configs with the real tools, the
same way `make check` and tests/promtool/rules_test.yml document they
should pass. Runs promtool/amtool inside their official Docker images, so
no local install of either binary is required.
"""
import re
import shutil
import subprocess
import tempfile
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


# The exact commented-out blocks docs/integrations.md tells a user to
# uncomment. Asserted present verbatim below before uncommenting, so this
# test fails loudly (not silently no-ops) if alertmanager.yml's comment
# text ever drifts from what's hardcoded here.
_PAGERDUTY_COMMENTED_BLOCK = """\
    # pagerduty_configs:
    #   - routing_key: '${PAGERDUTY_ROUTING_KEY}'
    #     severity: '{{ .CommonLabels.severity }}'
    #     description: '{{ .CommonAnnotations.summary }}'
    #     details:
    #       slo: '{{ .CommonLabels.slo }}'
    #       window: '{{ .CommonLabels.window }}'
    #       runbook: 'https://github.com/tenalisriharsha/slo-burn-rate-alerts/blob/main/docs/runbook.md'"""

_SLACK_COMMENTED_BLOCK = """\
    # slack_configs:
    #   - api_url: '${SLACK_WEBHOOK_URL}'
    #     channel: '#slo-tickets'
    #     title: '{{ .CommonLabels.alertname }}: {{ .CommonLabels.slo }}'
    #     text: >-
    #       {{ .CommonAnnotations.description }}
    #       (window={{ .CommonLabels.window }}, severity={{ .CommonLabels.severity }})
    #     send_resolved: true"""


def _uncommented(block: str) -> str:
    return "\n".join(re.sub(r"^(\s*)#\s?", r"\1", line) for line in block.split("\n"))


def test_amtool_check_config_passes_with_integration_blocks_uncommented():
    """docs/integrations.md's "Notes" section promises: "`make check`
    (`amtool check-config`) validates the YAML and Go template syntax of
    both blocks without needing real credentials - safe to run any time",
    and separately: "Alertmanager expands `${VAR}` references in its
    config file against its own process environment, so the secret itself
    never has to be written into `alertmanager.yml`". This follows those
    exact instructions - uncomment both receiver blocks, set the two env
    vars the docs name to dummy (non-real) values, run `amtool
    check-config` - and expects it to pass, as documented.
    """
    original = (REPO_ROOT / "alertmanager" / "alertmanager.yml").read_text()
    assert _PAGERDUTY_COMMENTED_BLOCK in original, "pagerduty block text has changed"
    assert _SLACK_COMMENTED_BLOCK in original, "slack block text has changed"
    uncommented = original.replace(
        _PAGERDUTY_COMMENTED_BLOCK, _uncommented(_PAGERDUTY_COMMENTED_BLOCK)
    ).replace(_SLACK_COMMENTED_BLOCK, _uncommented(_SLACK_COMMENTED_BLOCK))

    with tempfile.NamedTemporaryFile(
        "w", suffix=".yml", dir=REPO_ROOT / "alertmanager", delete=True
    ) as tmp:
        tmp.write(uncommented)
        tmp.flush()
        tmp_name = Path(tmp.name).name
        result = subprocess.run(
            [
                "docker",
                "run",
                "--rm",
                "-e",
                "PAGERDUTY_ROUTING_KEY=dummy-routing-key",
                "-e",
                "SLACK_WEBHOOK_URL=https://hooks.slack.example/dummy",
                "-v",
                f"{REPO_ROOT / 'alertmanager'}:/etc/alertmanager:ro",
                "--entrypoint",
                "amtool",
                ALERTMANAGER_IMAGE,
                "check-config",
                f"/etc/alertmanager/{tmp_name}",
            ],
            capture_output=True,
            text=True,
            timeout=90,
        )
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


def test_promtool_latency_rule_unit_tests_pass():
    """The latency SLO (Phase 3, PROGRESS.md) only had static YAML/regex
    threshold checks (tests/config/test_latency_alerting_rules.py) - unlike
    the availability and saturation SLOs, it had no promtool unit-test file
    actually simulating a burn through the real engine. This closes that
    gap with tests/promtool/latency_rules_test.yml, mirroring the pattern
    already used for the other two SLOs.
    """
    result = _run_promtool("test", "rules", "tests/promtool/latency_rules_test.yml")
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
