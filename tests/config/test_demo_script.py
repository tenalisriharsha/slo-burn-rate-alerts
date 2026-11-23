"""Checks for scripts/demo-incident.sh and the Makefile's `demo`/`burn`/
`reset` targets (README.md "Quick start", PROGRESS.md phase 2: "scripts
the manual `make burn` / `make reset` workflow into a single ramp/hold/
recover run"). Nothing previously asserted that the script's hardcoded
per-tier (rate, hold-seconds, `for`, alertname) table actually matches
prometheus/alerting_rules.yml - if the rules drift (e.g. a `for:` duration
is tuned), the demo would silently hold for the wrong amount of time and
never reach `firing`, with no test catching it.
"""
import json
import os
import re
import shutil
import signal
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
DEMO_SCRIPT = REPO_ROOT / "scripts" / "demo-incident.sh"
MAKEFILE = REPO_ROOT / "Makefile"
ALERTING_RULES = REPO_ROOT / "prometheus" / "alerting_rules.yml"
RECORDING_RULES = REPO_ROOT / "prometheus" / "recording_rules.yml"

TIER_ALERTNAME = {
    "fast": "SampleServiceErrorBudgetBurnFast",
    "medium-fast": "SampleServiceErrorBudgetBurnMediumFast",
    "slow": "SampleServiceErrorBudgetBurnSlow",
    "very-slow": "SampleServiceErrorBudgetBurnVerySlow",
}

# Fastest-to-slowest: alertmanager/alertmanager.yml inhibits every slower
# `window` label while a faster one is firing (window=fast inhibits
# window=~"medium-fast|slow|very-slow", etc.), so a demo tier's error rate
# must clear its own alert's threshold without also clearing any faster
# tier's threshold.
TIER_ORDER = ["fast", "medium-fast", "slow", "very-slow"]

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


def _error_budget() -> float:
    # sample_service:burnrateX records are "error_ratio / <error budget>"
    # (e.g. "sample_service:error_ratio:rate5m / 0.001"); every burnrate
    # record divides by the same constant, so the first match is enough.
    text = RECORDING_RULES.read_text()
    match = re.search(r"sample_service:error_ratio:rate\w+\s*/\s*([\d.]+)", text)
    assert match, "could not find the error-budget divisor in recording_rules.yml"
    return float(match.group(1))


def _tier_threshold_ratios() -> dict:
    """The minimum error ratio (0-1) each tier's own alert needs to fire,
    derived from its `expr`'s burn-rate multiplier (e.g. ">= 14.4") times
    the SLO error budget, i.e. the exact threshold prometheus evaluates -
    not a value copied from the issue report.
    """
    alerts = _alert_by_name()
    budget = _error_budget()
    ratios = {}
    for tier, alertname in TIER_ALERTNAME.items():
        expr = alerts[alertname]["expr"]
        multipliers = {float(n) for n in re.findall(r">=\s*([\d.]+)", expr)}
        assert len(multipliers) == 1, (
            f"{alertname}'s expr has inconsistent burn-rate thresholds: {multipliers}"
        )
        ratios[tier] = multipliers.pop() * budget
    return ratios


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


def test_script_incident_rate_crosses_only_its_own_tiers_threshold():
    """Each tier's INCIDENT_RATE must clear its own alert's burn-rate
    threshold without also clearing any faster tier's threshold (fast is
    always evaluated first). alertmanager/alertmanager.yml inhibits every
    slower `window` while a faster one is firing - e.g. window=fast
    inhibits window=~"medium-fast|slow|very-slow" - so if a slower tier's
    demo rate also crosses the fast tier's threshold, the fast alert fires
    first and the demo's own alert gets suppressed instead of routed (see
    README.md "Simulate an incident" and the acceptance criteria of the
    issue this guards: only the intended tier's alert should ever reach
    `firing`-and-routed for a given demo run).
    """
    tiers = _script_tiers()
    thresholds = _tier_threshold_ratios()

    for i, tier in enumerate(TIER_ORDER):
        incident_rate = float(tiers[tier]["rate"])
        assert incident_rate > thresholds[tier], (
            f"{tier}'s INCIDENT_RATE ({incident_rate}) does not even cross "
            f"its own alert's threshold ({thresholds[tier]})"
        )
        for faster_tier in TIER_ORDER[:i]:
            assert incident_rate <= thresholds[faster_tier], (
                f"{tier}'s INCIDENT_RATE ({incident_rate}) also crosses "
                f"{faster_tier}'s threshold ({thresholds[faster_tier]}), so "
                f"{faster_tier}'s alert would fire first and inhibit {tier}'s "
                f"alert in Alertmanager, exactly as described in issue #7"
            )


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


class _CapturingErrorRateHandler(BaseHTTPRequestHandler):
    """Stands in for sample-service's POST /error-rate - the demo script's
    only real dependency outside its own process - so the script's actual
    runtime behavior (not just its source text) can be exercised without
    bringing up the whole Flask app/docker stack.
    """

    requests: list

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length) or b"{}")
        self.requests.append(body)
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps({"error_rate": body.get("rate")}).encode())

    def log_message(self, *args):  # noqa: D102 - silence default stderr logging
        pass


@pytest.mark.skipif(shutil.which("bash") is None, reason="bash is required to run the script")
def test_script_actually_ramps_then_resets_to_baseline_on_sigint():
    """Behavioral check of the trap/cleanup claim
    test_script_resets_to_the_documented_healthy_baseline_on_exit only
    verifies via text presence: runs the real script (fast tier, which
    holds for HOLD_SECONDS=150s per the table above) against a stub
    /error-rate endpoint, sends it SIGINT partway through the hold, and
    asserts the trap actually fired - a real POST with the documented
    0.001 baseline rate reaching the stub server - not just that the
    script's source contains the word "trap".
    """
    received: list = []
    handler = type("Handler", (_CapturingErrorRateHandler,), {"requests": received})
    server = HTTPServer(("127.0.0.1", 0), handler)
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()
    try:
        url = f"http://127.0.0.1:{server.server_port}"
        proc = subprocess.Popen(
            ["bash", str(DEMO_SCRIPT), "fast", "--url", url],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            start_new_session=True,
        )
        try:
            deadline = time.monotonic() + 15
            while time.monotonic() < deadline and not received:
                time.sleep(0.1)
            assert received, "script never POSTed the incident rate to the stub server"
            assert received[0]["rate"] == pytest.approx(0.5)

            # Send SIGINT to the whole process group, not just bash's own
            # pid: bash is blocked inside `sleep ${HOLD_SECONDS}` (150s for
            # the fast tier), and signaling bash alone leaves that `sleep`
            # child running as an orphan holding the stdout/stderr pipes
            # open, which hangs communicate() for up to 150s.
            os.killpg(os.getpgid(proc.pid), signal.SIGINT)
            stdout, stderr = proc.communicate(timeout=15)
        finally:
            if proc.poll() is None:
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
                proc.communicate(timeout=5)
    finally:
        server.shutdown()
        server_thread.join(timeout=5)

    assert len(received) >= 2, f"expected a reset POST after SIGINT; got {received}\n{stdout}{stderr}"
    assert received[-1]["rate"] == pytest.approx(0.001)
