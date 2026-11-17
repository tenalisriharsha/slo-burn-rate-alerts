"""Checks for tonight's `integration-test` CI job (.github/workflows/ci.yml)
and the conftest.py skip wiring it depends on. README.md's "Status"
section and PROGRESS.md phase 5 both claim: CI itself brings up the real
docker-compose stack and asserts against the live Prometheus/Alertmanager
APIs via tests/integration/test_stack.py, and that this is the *only* CI
job that runs that Docker-gated test - `test-sample-service` is supposed
to skip it by default. A regression in either half (the YAML job or the
pytest skip logic) would silently turn that claim false without any
existing test failing.
"""
import subprocess
import sys
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
CI_FILE = REPO_ROOT / ".github" / "workflows" / "ci.yml"


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
