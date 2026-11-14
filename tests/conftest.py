"""Shared pytest configuration for the whole tests/ tree.

Registers the `integration` marker (tests/integration/test_stack.py) and
skips those tests by default, since they bring up the real docker-compose
stack and take several minutes. Run them explicitly with:

    RUN_INTEGRATION=1 pytest tests/integration -m integration
"""
import os

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "integration: brings up the real docker-compose stack and waits for an "
        "alert to fire; slow (several minutes) and requires Docker.",
    )


def pytest_collection_modifyitems(config, items):
    if os.environ.get("RUN_INTEGRATION"):
        return
    skip_integration = pytest.mark.skip(
        reason="set RUN_INTEGRATION=1 to run the docker-compose end-to-end test"
    )
    for item in items:
        if "integration" in item.keywords:
            item.add_marker(skip_integration)
