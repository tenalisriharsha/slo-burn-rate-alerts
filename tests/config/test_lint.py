"""Checks for the `make lint` target and its CI wiring, added this session
(README.md "Quick start": `make lint`; .github/workflows/ci.yml's
`lint-sample-service` job) and a real execution of the same check CI runs,
so a lint regression in sample-service/ fails here too.
"""
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]


def _ruff_binary() -> str | None:
    # Prefer the ruff installed alongside the interpreter running the tests
    # (e.g. a project venv's bin/) before falling back to PATH, since a venv
    # activated only for `python` won't necessarily put its bin/ on PATH.
    venv_ruff = Path(sys.executable).with_name("ruff")
    if venv_ruff.is_file():
        return str(venv_ruff)
    return shutil.which("ruff")


RUFF = _ruff_binary()


@pytest.mark.skipif(RUFF is None, reason="ruff is required to lint")
def test_ruff_check_passes_against_sample_service():
    result = subprocess.run(
        [RUFF, "check", "sample-service/"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_makefile_lint_target_runs_ruff_against_sample_service():
    makefile = (REPO_ROOT / "Makefile").read_text()
    assert "lint:" in makefile
    assert "ruff check sample-service/" in makefile


def test_ci_has_a_dedicated_lint_job_running_make_lint():
    ci_config = yaml.safe_load((REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text())
    jobs = ci_config["jobs"]
    assert "lint-sample-service" in jobs
    steps = jobs["lint-sample-service"]["steps"]
    assert any("make lint" in step.get("run", "") for step in steps)
