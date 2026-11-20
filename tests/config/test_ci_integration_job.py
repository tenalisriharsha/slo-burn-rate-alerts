"""Checks for tonight's `integration-test` CI job (.github/workflows/ci.yml)
and the conftest.py skip wiring it depends on. README.md's "Status"
section and PROGRESS.md phase 5 both claim: CI itself brings up the real
docker-compose stack and asserts against the live Prometheus/Alertmanager
APIs via tests/integration/test_stack.py, and that this is the *only* CI
job that runs that Docker-gated test - `test-sample-service` is supposed
to skip it by default. A regression in either half (the YAML job or the
pytest skip logic) would silently turn that claim false without any
existing test failing.

Also covers Phase 7 (PROGRESS.md / README "Status"): the `integration-test`
job is gated with an `if:` so it only runs automatically on a push to
`main`, or on demand via the workflow-level `workflow_dispatch` trigger -
every pull request should still skip it and only run the four fast jobs.
"""
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
CI_FILE = REPO_ROOT / ".github" / "workflows" / "ci.yml"

FAST_JOBS = (
    "validate-prometheus-config",
    "validate-alertmanager-config",
    "lint-sample-service",
    "test-sample-service",
)


def _load_ci_config() -> dict:
    return yaml.safe_load(CI_FILE.read_text())


def _job_run_steps(job: dict) -> list[str]:
    return [step.get("run", "") for step in job["steps"]]


def test_integration_test_job_exists():
    jobs = _load_ci_config()["jobs"]
    assert "integration-test" in jobs


def test_integration_test_job_runs_on_ubuntu_latest():
    job = _load_ci_config()["jobs"]["integration-test"]
    assert job["runs-on"] == "ubuntu-latest"


def test_integration_test_job_checks_out_and_sets_up_python():
    job = _load_ci_config()["jobs"]["integration-test"]
    uses = [step.get("uses", "") for step in job["steps"]]
    assert any(u.startswith("actions/checkout") for u in uses)
    assert any(u.startswith("actions/setup-python") for u in uses)


def test_integration_test_job_installs_runtime_deps_and_requests():
    job = _load_ci_config()["jobs"]["integration-test"]
    install_steps = " ".join(_job_run_steps(job))
    assert "sample-service/requirements.txt" in install_steps
    assert "pytest" in install_steps
    assert "requests" in install_steps


def test_integration_test_job_runs_the_docker_compose_test_with_run_integration_set():
    job = _load_ci_config()["jobs"]["integration-test"]
    run_step = next(
        step for step in job["steps"] if "pytest tests/integration" in step.get("run", "")
    )
    assert run_step.get("env", {}).get("RUN_INTEGRATION") == "1"
    assert "-m integration" in run_step["run"]


def test_test_sample_service_job_does_not_set_run_integration():
    # The docstring in tests/conftest.py and the comment on integration-test
    # both say this job alone needs RUN_INTEGRATION=1, and that
    # test-sample-service skips the integration test by default. If someone
    # copies the env block onto the wrong job, the slow Docker-gated test
    # would start running on every PR via test-sample-service too.
    job = _load_ci_config()["jobs"]["test-sample-service"]
    for step in job["steps"]:
        assert step.get("env", {}).get("RUN_INTEGRATION") is None


def test_readme_status_documents_the_live_ci_integration_test():
    readme = (REPO_ROOT / "README.md").read_text()
    status_section = readme.split("## Status", 1)[1]
    assert "integration-test" in status_section
    assert "docker-compose" in status_section


def test_integration_tests_are_skipped_by_default(monkeypatch):
    # Behavioral check of tests/conftest.py's pytest_collection_modifyitems:
    # this is exactly what keeps the slow, Docker-gated test out of the
    # fast, default `pytest` run (CI's test-sample-service job), and is
    # never actually exercised by the structural YAML checks above.
    monkeypatch.delenv("RUN_INTEGRATION", raising=False)
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "tests/integration", "-v"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "skipped" in result.stdout.lower()
    assert "passed" not in result.stdout.lower()


def _load_triggers() -> dict:
    # PyYAML's safe_load resolves the bare `on:` key as the boolean True
    # (YAML 1.1's on/off/yes/no boolean aliases), not the string "on".
    return _load_ci_config()[True]


def test_workflow_has_a_workflow_dispatch_trigger():
    assert "workflow_dispatch" in _load_triggers()


def test_workflow_still_triggers_on_push_to_main_and_on_pull_request():
    # The gating `if:` below only matters if the workflow itself keeps
    # listening for these two events - if either trigger were dropped, the
    # `if:` condition could never become true (push) or the fast jobs would
    # stop running on PRs (pull_request) without any existing check noticing.
    triggers = _load_triggers()
    assert "main" in triggers["push"]["branches"]
    assert "pull_request" in triggers


def test_integration_test_job_has_the_documented_if_condition():
    job = _load_ci_config()["jobs"]["integration-test"]
    assert job["if"] == (
        "github.event_name == 'workflow_dispatch' || "
        "(github.event_name == 'push' && github.ref == 'refs/heads/main')"
    )


def _integration_test_runs(event_name: str, ref: str) -> bool:
    """Evaluate the integration-test job's actual `if:` string for a given
    (event_name, ref), the same way GitHub Actions would, instead of just
    pattern-matching the expression text. The expression only ever
    references github.event_name/github.ref and the &&/||/== operators
    GitHub Actions expressions support, so substituting those two values
    and translating the operators to Python is a faithful evaluation of
    the real condition, not just of today's exact wording.
    """
    expr = _load_ci_config()["jobs"]["integration-test"]["if"]
    expr = expr.replace("github.event_name", repr(event_name))
    expr = expr.replace("github.ref", repr(ref))
    expr = expr.replace("&&", " and ").replace("||", " or ")
    return bool(eval(expr))  # noqa: S307 - expr is this repo's own trusted YAML


@pytest.mark.parametrize(
    ("event_name", "ref", "expected"),
    [
        ("push", "refs/heads/main", True),
        ("push", "refs/heads/night/2026-11-20", False),
        ("pull_request", "refs/heads/main", False),
        ("workflow_dispatch", "refs/heads/main", True),
        ("workflow_dispatch", "refs/heads/some-feature", True),
    ],
)
def test_integration_test_job_if_condition_gates_on_push_to_main_or_manual_dispatch(
    event_name, ref, expected
):
    assert _integration_test_runs(event_name, ref) is expected


@pytest.mark.parametrize("job_name", FAST_JOBS)
def test_fast_jobs_have_no_if_condition_so_they_always_run_on_a_pull_request(job_name):
    # README's "Status" section promises every PR still gets these four
    # jobs unconditionally - only integration-test should be gated.
    job = _load_ci_config()["jobs"][job_name]
    assert "if" not in job


def test_readme_status_documents_the_integration_test_trigger_gating():
    readme = (REPO_ROOT / "README.md").read_text()
    status_section = readme.split("## Status", 1)[1]
    assert "workflow_dispatch" in status_section
    assert "main" in status_section
