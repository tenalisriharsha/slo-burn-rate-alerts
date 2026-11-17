"""Checks for scripts/demo-incident.sh and the Makefile's `demo`/`burn`/
`reset` targets (README.md "Quick start", PROGRESS.md phase 2: "scripts
the manual `make burn` / `make reset` workflow into a single ramp/hold/
recover run"). Nothing previously asserted that the script's hardcoded
per-tier (rate, hold-seconds, `for`, alertname) table actually matches
prometheus/alerting_rules.yml - if the rules drift (e.g. a `for:` duration
is tuned), the demo would silently hold for the wrong amount of time and
never reach `firing`, with no test catching it.
"""
import re
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
DEMO_SCRIPT = REPO_ROOT / "scripts" / "demo-incident.sh"
MAKEFILE = REPO_ROOT / "Makefile"
ALERTING_RULES = REPO_ROOT / "prometheus" / "alerting_rules.yml"

TIER_ALERTNAME = {
    "fast": "SampleServiceErrorBudgetBurnFast",
    "medium-fast": "SampleServiceErrorBudgetBurnMediumFast",
    "slow": "SampleServiceErrorBudgetBurnSlow",
    "very-slow": "SampleServiceErrorBudgetBurnVerySlow",
}

TIER_BLOCK = re.compile(
    r'(?P<tier>fast|medium-fast|slow|very-slow)\)\s*'
    r'INCIDENT_RATE="(?P<rate>[\d.]+)"\s*'
    r'HOLD_SECONDS=(?P<hold>\d+)\s*'
    r'ALERT_FOR="(?P<for>\w+)"\s*'
    r'ALERT_NAME="(?P<alertname>\w+)"',
)


def _script_tiers() -> dict:
    text = DEMO_SCRIPT.read_text()
    return {m["tier"]: m.groupdict() for m in TIER_BLOCK.finditer(text)}


def _alert_by_name() -> dict:
    rules = yaml.safe_load(ALERTING_RULES.read_text())
    alerts = rules["groups"][0]["rules"]
    return {rule["alert"]: rule for rule in alerts}


def test_script_defines_all_four_documented_tiers():
    assert set(_script_tiers().keys()) == set(TIER_ALERTNAME.keys())


def test_script_alertnames_match_the_tiers_documented_name():
    tiers = _script_tiers()
    for tier, alertname in TIER_ALERTNAME.items():
        assert tiers[tier]["alertname"] == alertname


def test_script_alert_for_matches_the_rule_files_for_duration():
    tiers = _script_tiers()
    alerts = _alert_by_name()
    for tier, alertname in TIER_ALERTNAME.items():
        assert tiers[tier]["for"] == str(alerts[alertname]["for"])


def test_script_hold_duration_is_at_least_the_alert_for_duration():
    # The demo can only ever reach `firing` if it holds the incident rate
    # for at least the alert's `for:` duration.
    unit_seconds = {"m": 60, "h": 3600}
    tiers = _script_tiers()
    alerts = _alert_by_name()
    for tier, alertname in TIER_ALERTNAME.items():
        for_duration = str(alerts[alertname]["for"])
        for_seconds = int(for_duration[:-1]) * unit_seconds[for_duration[-1]]
        assert int(tiers[tier]["hold"]) >= for_seconds


def test_script_resets_to_the_documented_healthy_baseline_on_exit():
    text = DEMO_SCRIPT.read_text()
    assert 'BASELINE_RATE="0.001"' in text
    assert "trap reset_to_baseline EXIT" in text


def test_makefile_demo_target_runs_the_script():
    makefile = MAKEFILE.read_text()
    assert "demo:" in makefile
    assert "scripts/demo-incident.sh" in makefile


def test_makefile_burn_and_reset_targets_hit_the_error_rate_endpoint():
    makefile = MAKEFILE.read_text()
    assert "burn:" in makefile
    assert "reset:" in makefile
    assert "localhost:8000/error-rate" in makefile
    # reset must put the service back at the documented healthy baseline.
    reset_block = makefile.split("reset:", 1)[1].split("demo:", 1)[0]
    assert '"rate": 0.001' in reset_block
