"""Structural checks on alertmanager/alertmanager.yml: severity-based
routing to page/ticket (README.md, docs/runbook.md) and the inhibition
chain that stops a faster tier's incident from also filing a slower
tier's ticket (PROGRESS.md phase 1/2, docs/integrations.md).
"""
import re
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
CONFIG_FILE = REPO_ROOT / "alertmanager" / "alertmanager.yml"


def _load():
    return yaml.safe_load(CONFIG_FILE.read_text())


def test_default_route_groups_by_alertname_and_slo():
    route = _load()["route"]
    assert route["receiver"] == "default"
    assert "alertname" in route["group_by"]
    assert "slo" in route["group_by"]


def test_critical_severity_routes_to_page_receiver():
    routes = _load()["route"]["routes"]
    critical = [r for r in routes if r["matchers"] == ['severity="critical"']]
    assert len(critical) == 1
    assert critical[0]["receiver"] == "page"


def test_warning_severity_routes_to_ticket_receiver():
    routes = _load()["route"]["routes"]
    warning = [r for r in routes if r["matchers"] == ['severity="warning"']]
    assert len(warning) == 1
    assert warning[0]["receiver"] == "ticket"


def test_default_page_and_ticket_receivers_all_exist():
    names = {r["name"] for r in _load()["receivers"]}
    assert names == {"default", "page", "ticket"}


def test_page_and_ticket_receivers_have_no_active_integration_by_default():
    """No webhook URL or API key may ever be committed (docs/integrations.md)."""
    for receiver in _load()["receivers"]:
        if receiver["name"] in ("page", "ticket"):
            assert "pagerduty_configs" not in receiver
            assert "slack_configs" not in receiver


def test_commented_pagerduty_and_slack_blocks_use_env_var_placeholders_only():
    """docs/integrations.md tells users to set an env var and uncomment the
    block, never to paste a credential in directly. YAML-structural checks
    (and `amtool check-config`) can't see commented-out lines at all, so a
    key/URL literal pasted in place of ${VAR} - leaving the line commented,
    or even after uncommenting - would pass every other check here.
    """
    text = CONFIG_FILE.read_text()
    for line in text.splitlines():
        stripped = line.strip().lstrip("#").strip()
        match = re.match(r"(routing_key|api_url):\s*'([^']*)'", stripped)
        if match:
            value = match.group(2)
            assert value.startswith("${") and value.endswith("}"), (
                f"expected an env-var placeholder, found a literal value: {line!r}"
            )


def test_inhibit_rules_form_a_chain_from_fast_down_to_very_slow():
    inhibit_rules = _load()["inhibit_rules"]
    pairs = {
        (rule["source_matchers"][0], rule["target_matchers"][0]) for rule in inhibit_rules
    }
    assert ('window="fast"', 'window=~"medium-fast|slow|very-slow"') in pairs
    assert ('window="medium-fast"', 'window=~"slow|very-slow"') in pairs
    assert ('window="slow"', 'window="very-slow"') in pairs
    for rule in inhibit_rules:
        assert rule["equal"] == ["slo"]
