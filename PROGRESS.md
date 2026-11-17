# Progress

## Vision

A reference implementation of Google SRE-style multi-window multi-burn-rate
alerting: Prometheus recording rules and Alertmanager routes for three
independent SLOs (availability, latency, and saturation) on a sample
service, with a runbook explaining the math and false-positive tradeoffs.

## Architecture

```
sample-service (Flask + prometheus_client)
    - exposes /metrics (http_requests_total{code}, http_request_duration_seconds,
      sample_service_queue_depth)
    - POST /error-rate, POST /slow-rate, POST /queue-depth let a demo script simulate an incident
        |
        v
Prometheus
    - scrapes sample-service
    - recording_rules.yml + latency_recording_rules.yml + saturation_recording_rules.yml:
      error ratio / latency ratio / saturation ratio + burn rate, each over
      7 windows (5m, 30m, 1h, 2h, 6h, 1d, 3d)
    - alerting_rules.yml + latency_alerting_rules.yml + saturation_alerting_rules.yml:
      4 multi-window multi-burn-rate alert tiers per SLO (12 alerts total)
        |              \
        v               v
Alertmanager          Grafana
    - routes severity=critical       - provisioned dashboard: burn rate
      -> "page" receiver               per window (all 3 SLOs), error-budget
    - routes severity=warning          gauge, p99 latency estimate, queue
      -> "ticket" receiver               depth vs threshold, request/error
    - inhibits slower tiers once a      rate, live alerts
      faster tier is already firing (per SLO)
```

Everything is wired together with `docker-compose.yml` so the whole stack
(including synthetic traffic) runs with one command - see the README quick
start. `scripts/demo-incident.sh` (`make demo`) scripts the manual
`make burn` / `make reset` workflow into a single ramp/hold/recover run for
the availability SLO; the latency SLO is driven the same way via
`POST /slow-rate`.

## Phased build plan

### Phase 1 - Scaffold + core foundation (done)

- [x] Repo scaffold: directory layout, `.gitignore`, `LICENSE`, `Makefile`,
      CI workflow skeleton (promtool/amtool validation + pytest hook)
- [x] `sample-service`: Flask app exposing `/metrics`, synthetic traffic
      generator, runtime-adjustable error rate via `/error-rate`
- [x] `prometheus/recording_rules.yml`: error ratio + burn rate recording
      rules across 7 windows
- [x] `prometheus/alerting_rules.yml`: 4-tier multi-window multi-burn-rate
      alerts (fast/medium-fast page, slow/very-slow ticket)
- [x] `alertmanager/alertmanager.yml`: severity-based routing (page/ticket)
      + inhibition rules so slower tiers don't double-alert on the same
      incident
- [x] `docker-compose.yml` demo stack (sample-service + Prometheus +
      Alertmanager)
- [x] Validated `promtool check config`, `promtool check rules`, and
      `amtool check-config` all pass
- [x] Ran the full stack for real: raised the sample service's error rate
      and confirmed all 4 alert tiers reach `pending`/`firing` in
      Prometheus and route correctly in Alertmanager
- [x] `docs/runbook.md`: the burn-rate math, the 4-tier table, and the
      false-positive/false-negative tradeoff discussion
- [x] README with quick start + preview screenshots

### Phase 2 - Visualization + routing depth (done)

- [x] Grafana service added to `docker-compose.yml` (`localhost:3000`,
      anonymous viewer access, admin/admin), auto-provisioned with a
      Prometheus datasource (`grafana/provisioning/datasources/`) and a
      dashboard provider (`grafana/provisioning/dashboards/`)
- [x] `grafana/dashboards/slo-burn-rate.json`: 4 panels - burn rate across
      all 7 windows, a "days until budget exhausted" gauge
      (`30 / sample_service:burnrate1h`), request vs error rate, and a
      live table of `ALERTS{slo="sample-service-availability"}`
- [x] `scripts/demo-incident.sh`: drives `POST /error-rate` through a
      ramp/hold/recover cycle for any of the 4 tiers (`make demo
      TIER=<tier>`); always resets to baseline on exit via a trap, even on
      Ctrl-C
- [x] `alertmanager/alertmanager.yml`: `page`/`ticket` receivers now carry
      complete (commented-out) `pagerduty_configs`/`slack_configs` blocks
      with real field names and Go templating, referencing `${VAR}`
      env-var placeholders instead of embedding any credential
- [x] `docs/integrations.md`: step-by-step instructions to get a PagerDuty
      integration key / Slack webhook, set it as an env var, and uncomment
      the matching block
- [x] Ran the real stack again end-to-end (`docker compose up`, `make
      demo TIER=fast`): confirmed Grafana auto-loads the datasource and
      dashboard with no manual clicking, the dashboard panels populate with
      real data during the simulated incident, and `make check` still
      passes after the alertmanager.yml edits
- [x] promtool rule unit tests (`tests/promtool/rules_test.yml`, owned by
      the test suite) already cover each alert tier's threshold boundaries

### Phase 3 - Polish (done)

- [x] Second SLO profile example (latency-based, p99 < 300ms): a
      `http_request_duration_seconds` histogram and a `/slow-rate` knob in
      `sample-service/app.py` (mirroring `/error-rate`), plus
      `prometheus/latency_recording_rules.yml` +
      `prometheus/latency_alerting_rules.yml` reusing the identical
      multi-window multi-burn-rate method and thresholds, with their own
      `slo: sample-service-latency` label so they route through the
      existing severity-based Alertmanager rules unchanged
- [x] Architecture diagram image for the README (`docs/architecture.png`,
      rendered from a hand-built SVG, not a generated/AI image)
- [x] CI: promtool rule unit tests already run as part of `pytest` in the
      `test-sample-service` job (`tests/promtool/test_promtool.py`); added
      a `lint-sample-service` CI job running `make lint` (ruff) against
      `sample-service/`
- [x] Final documentation pass: README quick start re-verified command by
      command against a fresh `git clone` into an empty directory
      (`make up`, `make check`, `make lint`, `make burn`/`make reset`, the
      `/slow-rate` curls, `make down`) - all passed as written

### Also fixed in the Phase 3 session

- [x] CI was red on PR #1 (`validate-prometheus-config` and
      `validate-alertmanager-config` both failing): those jobs ran inside
      `container: prom/prometheus:latest` / `prom/alertmanager:latest`, but
      `actions/checkout` is a JS action and those images have no Node.js
      runtime, so checkout itself failed with "exec
      /__e/node24/bin/node: no such file or directory". Fixed by running
      the jobs on the normal `ubuntu-latest` runner and shelling out to
      `make check-prometheus` / `make check-alertmanager`, which already
      validate correctly via `docker run` against a mounted volume (the
      same thing `make check` has always done locally).

### Phase 4 - Third SLO shape: saturation on a gauge (done)

- [x] `sample-service/app.py`: a `sample_service_queue_depth` Gauge and a
      `/queue-depth` knob (mirroring `/error-rate`/`/slow-rate`) that sets
      the target depth the synthetic traffic loop jitters around each tick
- [x] `prometheus/saturation_recording_rules.yml`: the adaptation this
      phase exists to demonstrate - `sample_service:queue_saturated:bool`
      turns the gauge into a `1`/`0` indicator via `> bool 50` on every
      evaluation (which itself becomes a real recorded time series), then
      `avg_over_time()` over the same 7 windows gives "fraction of time
      saturated", the same ratio shape as the error/latency ratios; burn
      rate divides by the budget (`0.02`) exactly as before
- [x] `prometheus/saturation_alerting_rules.yml`: the identical 4-tier
      thresholds/`for` durations, `slo: sample-service-saturation`, routes
      through the existing severity-based Alertmanager rules unchanged
- [x] `prometheus/prometheus.yml` + `Makefile`'s `check-prometheus`:
      wired in the two new rule files
- [x] `grafana/dashboards/slo-burn-rate.json`: 3 new panels - saturation
      burn rate by window, queue depth vs the 50-item threshold, and the
      live saturation alert table
- [x] `docs/runbook.md`: new "Saturation SLO" section explaining the
      gauge-to-indicator adaptation and its cost (resolution capped at
      `evaluation_interval`, so a sub-15s spike can average away)
- [x] `docs/architecture.png` regenerated to show all 3 SLOs end to end
- [x] README: third SLO documented in the quick start, the SLO table, the
      architecture diagram, and the repository layout; 3 new preview
      screenshots (saturation alerts, saturation burn-rate graph, Grafana
      saturation panels)
- [x] Ran the real stack: `POST /queue-depth {"target": 80}` drove all 4
      saturation alert tiers from `inactive` through `pending` to
      `firing`, confirmed via the live Prometheus rules API

### Phase 5 - Run the real stack in CI, not just validate its YAML (done)

- [x] `.github/workflows/ci.yml`: new `integration-test` job that installs
      the sample-service's runtime deps + `pytest`/`requests` and runs
      `RUN_INTEGRATION=1 pytest tests/integration -m integration -v` on the
      standard `ubuntu-latest` runner (Docker and Docker Compose are
      preinstalled there, so no extra setup step is needed). This is
      exactly `tests/integration/test_stack.py`, previously only runnable
      locally - it brings up the real `sample-service` + `prometheus` +
      `alertmanager` containers, drives a simulated incident through each
      of the error-rate and queue-depth knobs, and asserts the fast-tier
      alert for both the availability and saturation SLOs reaches
      `state=firing` in Prometheus and shows up in Alertmanager routed
      with `severity=critical` - closing the gap the other CI jobs leave
      (`validate-prometheus-config`/`validate-alertmanager-config` only
      config-validate the YAML; `test-sample-service` skips the
      integration test by default per `tests/conftest.py`)
- [x] Ran the real thing locally exactly as the new CI job will:
      `RUN_INTEGRATION=1 pytest tests/integration -m integration -v`
      against a clean `docker compose` stack - both tests passed, each
      fast-tier alert reached `firing` and routed to `page` in
      Alertmanager
- [x] README's Status section now mentions CI exercises the live stack,
      not only its config

## Resume point

All five phases are complete. The full test suite passes (164 passed, 2
skipped - the 2 skips are the Docker-gated integration tests, which were
also run explicitly this session and passed), `make check` and `make
lint` pass, and the real docker-compose stack was exercised live again
this session.

Ideas for a future session (not required, nothing left is broken):

- Rotating/randomized synthetic traffic patterns (daily seasonality) so the
  burn-rate graphs in the README screenshots look less like a flat line
  before an incident.
- The `integration-test` CI job takes several minutes (it waits for a real
  burn-rate window to clear its threshold) - if that becomes annoying on
  every PR, consider gating it to `push` on `main` only, or adding
  `workflow_dispatch` so it can also be run on demand.

## Known gap: published repo is stale

An independent clean-environment verification pass (2026-11-15) ran the
README's quick start against the *published* GitHub repository
(`github.com/tenalisriharsha/slo-burn-rate-alerts`, branch `main`) and
failed: `main` there is several commits behind this branch's content - it
has no `grafana/` directory, no `scripts/demo-incident.sh`, no `tests/`
suite, and no latency SLO (`latency_recording_rules.yml` /
`latency_alerting_rules.yml`), and its `docker-compose.yml` only defines 3
services (no Grafana), so `make up` there never brings up `localhost:3000`
as the README describes.

This is not a code or README defect: every file the README references
(the `grafana/` dir, `scripts/demo-incident.sh`, `tests/`, the latency
rule files, the 4-service `docker-compose.yml`) already exists in this
branch's working tree, confirmed again on 2026-11-15. The gap is purely
that `main` on GitHub has not been fast-forwarded/merged to include this
branch's commits. Fixing it requires a `git push`/merge to `main`, which
is outside what an unattended coding session should do without the user's
explicit sign-off (pushing/rewriting a shared branch's history is exactly
the kind of action that needs confirmation first). Next session (or the
user directly): fast-forward or merge `main` to the tip of this branch and
push, then the README's quick start will work against a fresh clone as
written.

STATUS: COMPLETE (pending the push/merge above to make the published repo match)
