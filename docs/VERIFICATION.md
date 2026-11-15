# Verification

This document records a first-time-user style verification of this project,
run in a fresh clone outside the working tree.

## First-use check

Followed the README's quick start section word for word:

```bash
git clone https://github.com/tenalisriharsha/slo-burn-rate-alerts.git
cd slo-burn-rate-alerts
make up
```

Expected (per README): the clone gets the project as currently documented,
`make up` builds and starts four containers (sample-service, Prometheus,
Alertmanager, and Grafana with a provisioned dashboard and anonymous viewer
access at `localhost:3000`).

Observed: `git clone https://github.com/tenalisriharsha/slo-burn-rate-alerts.git`
checks out the `main` branch, which contains only 5 commits (scaffold,
sample service, availability alerting rules, Alertmanager routing, and an
early README/runbook). It does **not** contain the `grafana/` directory,
`scripts/demo-incident.sh`, the `tests/` suite, or the latency SLO
(`latency_recording_rules.yml`, `latency_alerting_rules.yml`). Its
`docker-compose.yml` defines only three services (sample-service,
Prometheus, Alertmanager) — there is no Grafana service at all, so
`localhost:3000` never comes up. Running `make up` against that clone
succeeds and starts three containers, but the README text being followed
(the one in this working directory, describing four containers, a Grafana
dashboard, and a second latency SLO) does not match what the published
repository actually provides. A first-time user pasting the quick-start
commands verbatim gets a stack that contradicts the README they just read.

To still exercise the project's current, intended behavior, verification
continued against a fresh clone of the local repository at its current
branch (equivalent in content to this working directory) in a new temporary
directory, with `make up` run there instead:

- `make up` built the sample-service image and started all four containers
  (sample-service, prometheus, alertmanager, grafana), as the current
  README describes.
- `curl localhost:8000/metrics` → `200`
- `curl localhost:9090/-/healthy` → `200`
- `curl localhost:9093/-/healthy` → `200`
- `curl localhost:3000/api/health` → `200`, `{"database":"ok", ...}`
- `curl localhost:3000/api/search` (no auth) → returned the provisioned
  `SLO Burn Rate - sample-service` dashboard, confirming anonymous viewer
  access works as documented.
- `make check` → promtool validated `recording_rules.yml` (28 rules),
  `alerting_rules.yml` (4 rules), `latency_recording_rules.yml` (21 rules),
  `latency_alerting_rules.yml` (4 rules); amtool validated
  `alertmanager.yml` (3 inhibit rules, 3 receivers). All succeeded.

Result: FAIL - the README's quick-start `git clone` command points at a
published repository whose default branch is several commits behind this
project's current state, so it lacks Grafana, the latency SLO, and other
features the current README describes; the rest of this check (and the
sections below) was run against a fresh clone of the project's current
content instead, which passed.

## Headline feature run

With the four-container stack (built from the current project content, per
the note above) running, simulated the documented availability incident:

```bash
make burn RATE=0.5
```

Expected (per README): burn-rate alerts move `inactive` → `pending` →
`firing` as the error rate stays elevated.

Observed, polling `localhost:9090/api/v1/rules`:
- t=10s: `SampleServiceErrorBudgetBurnFast` = `pending`,
  `sample_service:burnrate5m` ≈ 580x (threshold is 14.4x)
- t=120s: `SampleServiceErrorBudgetBurnFast` = `firing`, matching the
  documented `for: 2m`
- `curl localhost:9093/api/v2/alerts` showed the alert received by
  Alertmanager, `severity: critical`, routed to the `page` receiver,
  exactly matching the tier table in the README.

```bash
make reset
```
cleared the error rate back to `0.001` and the alert state back down.

Then simulated the independent latency incident:

```bash
curl -X POST localhost:8000/slow-rate -H 'Content-Type: application/json' -d '{"rate": 0.9}'
```

Observed: `SampleServiceLatencyBudgetBurnFast` went `pending` at t=60s with
`sample_service:latency_burnrate5m` ≈ 18.4x (past the 14.4x threshold),
confirming the latency SLO behaves the same way as the availability one, as
the README claims. Reset `slow-rate` back to `0.001`.

Finally ran the scripted demo:

```bash
make demo
```

Expected: ramps error rate to 50%, holds 150s, auto-recovers.

Observed: script output showed `[1/3] ramping error rate to 0.5`,
`[2/3] holding at 0.5 for 150s`, `[3/3] incident window complete`, then
`-> error rate reset to the healthy baseline (0.001)`, exit code 0.

Result: PASS

## Test suite with development tools

In the same fresh clone, created a Python 3.12 virtual environment (matching
the version CI's `lint-sample-service` and `test-sample-service` jobs use)
and installed the project's dependencies plus `pytest`:

```bash
python3.12 -m venv .venv
.venv/bin/pip install -r sample-service/requirements.txt -r sample-service/requirements-dev.txt pytest
```

Ran the lint check documented in the README:

```bash
make lint
```
Observed: `ruff check sample-service/` → `All checks passed!`

Ran the full test suite:

```bash
pytest -q
```
Observed: `113 passed, 1 skipped in 11.31s`. The one skip was
`tests/integration/test_stack.py`, which the test itself reports is gated
behind `RUN_INTEGRATION=1` since it spins up its own docker-compose stack.
Ran it explicitly:

```bash
RUN_INTEGRATION=1 pytest tests/integration/test_stack.py
```
Observed: `1 passed in 170.86s` — the test builds its own stack, drives the
same simulated incident, waits for the fast-burn tier to actually fire, and
confirms Alertmanager routes it to the `page` receiver, then tears its stack
down.

Also re-ran the config validation documented in the README:

```bash
make check
```
Observed: all promtool and amtool checks passed (see First-use check above
for the detailed output).

Result: PASS
