# Verification

This document records a first-time-user style verification of this project,
run in a fresh clone outside the working tree (Docker Desktop, macOS,
Docker Compose v5, Python 3.15).

## First-use check

Followed the README's quick start section word for word, against the
actual published repository:

```bash
git clone https://github.com/tenalisriharsha/slo-burn-rate-alerts.git
cd slo-burn-rate-alerts
make up
```

Expected (per README): `make up` builds and starts four containers
(sample-service, Prometheus, Alertmanager, Grafana), with Grafana reachable
anonymously at `localhost:3000`.

Observed: the clone checked out `main` at commit `500f94a`. `make up` built
the sample-service image and started all four containers
(`sample-service`, `prometheus`, `alertmanager`, `grafana`) without errors.
After a few seconds:

- `curl localhost:8000/metrics` → `200`
- `curl localhost:9090/-/ready` → `200`, `Prometheus Server is Ready.`
- `curl localhost:9093/-/healthy` → `200`
- `curl localhost:3000/api/health` → `200`, `{"database":"ok", ...}`

`make down` cleanly stopped and removed all four containers and the
network. This matches the README exactly, with no undocumented steps
needed. (Note: an earlier verification pass of this project, made before
recent commits landed on `main`, had found the published branch several
commits behind - missing Grafana, the latency/saturation SLOs, and the
test suite. That gap has since closed: the published `main` branch's
`README.md`, `docker-compose.yml`, `prometheus/`, `sample-service/`,
`grafana/`, and `scripts/` are now byte-identical to this repository's
working tree.)

Result: PASS

## Headline feature run

Brought the four-container stack up again and ran the documented
availability incident:

```bash
make burn RATE=0.5
```

Expected (per README): burn-rate alerts move `inactive` → `pending` →
`firing` as the error rate stays elevated.

Observed, polling `localhost:9090/api/v1/rules` for
`SampleServiceErrorBudgetBurnFast`:

- baseline (before the burn): `inactive`
- ~30s after the burn: `pending`
- ~2m40s after the burn (matching the rule's `for: 2m` plus propagation
  delay): `firing`
- `curl localhost:9093/api/v2/alerts` showed the alert received by
  Alertmanager with `severity: critical` and `status.state: active`,
  matching the "page" tier in the README's table

```bash
make reset
```
cleared the error rate back to `0.001`.

Exercised the other two independent SLO knobs documented in the README:

```bash
curl -X POST localhost:8000/slow-rate -H 'Content-Type: application/json' -d '{"rate": 0.9}'
curl -X POST localhost:8000/slow-rate -H 'Content-Type: application/json' -d '{"rate": 0.001}'
curl -X POST localhost:8000/queue-depth -H 'Content-Type: application/json' -d '{"target": 80}'
curl -X POST localhost:8000/queue-depth -H 'Content-Type: application/json' -d '{"target": 5}'
```
Observed: each call returned the expected JSON echo (`{"slow_rate":0.9}`,
`{"queue_depth_target":80.0}`, etc.) with no errors.

Ran the scripted demo:

```bash
make demo
```
Expected: ramps error rate to 50%, holds 150s, auto-recovers.

Observed: output showed `[1/3] ramping error rate to 0.5`, `[2/3] holding
at 0.5 for 150s`, `[3/3] incident window complete`, then `-> error rate
reset to the healthy baseline (0.001)`, exit code 0. The fast-tier alert
had reached `pending` by the end of the hold window.

Validated configs and lint, also documented in the quick start:

```bash
make check    # promtool + amtool validation of all rule/config files - all succeeded
make lint     # ruff check sample-service/ -> All checks passed!
```

This project has no LLM-calling component, so no `claude -p` calls were
applicable here; the headline feature is the burn-rate alerting pipeline
itself, exercised above against the real, unmocked stack.

`make down` cleanly tore down the stack afterward.

Result: PASS

## Test suite with development tools

In a fresh clone, created a Python virtual environment and installed the
project's declared dependencies plus `pytest`/`requests` (used by the
integration suite):

```bash
python3 -m venv .venv
.venv/bin/pip install -r sample-service/requirements.txt -r sample-service/requirements-dev.txt pytest requests
```

Ran the lint check documented in the README:

```bash
make lint
```
Observed: `ruff check sample-service/` → `All checks passed!` (the project
documents and uses `ruff`; it does not use `mypy` or any other type
checker).

Ran the full non-integration test suite:

```bash
pytest -q --ignore=tests/integration
```
Observed: `218 passed in 150.69s`, covering config validation
(`tests/config/`), promtool-based rule unit tests (`tests/promtool/`), and
sample-service unit tests (`tests/unit/`).

Ran the real docker-compose integration suite explicitly (Docker is
available), which brings up its own stack under a separate compose project
name, drives a real incident, and tears itself down:

```bash
RUN_INTEGRATION=1 pytest tests/integration -m integration -v
```
Observed:
```
tests/integration/test_stack.py::test_simulated_incident_fires_the_fast_tier_alert_and_routes_to_page PASSED
tests/integration/test_stack.py::test_simulated_saturation_incident_fires_the_fast_tier_alert_and_routes_to_page PASSED
2 passed in 330.68s (0:05:30)
```
Confirmed via `docker ps -a` afterward that the test's own containers were
removed and no stack was left running.

Re-ran config validation one more time for completeness:

```bash
make check
```
Observed: all promtool and amtool checks passed.

Result: PASS
