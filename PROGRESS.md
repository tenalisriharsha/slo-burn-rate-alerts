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

### Also fixed: flaky `test_promtool_saturation_rule_unit_tests_pass` on PR #3's CI

- [x] CI's `test-sample-service` job was red on PR #3
      (`tests/promtool/test_promtool.py::test_promtool_saturation_rule_unit_tests_pass`),
      failing intermittently (not every run) at the fast tier's 65-minute
      boundary case. Reproduced locally: looping the same `promtool test
      rules tests/promtool/saturation_rules_test.yml` invocation 15 times
      against the unchanged rule files failed ~20-30% of the time with
      "got:[]" where an alert was expected, with no code or test change
      between runs - a genuine race, not a one-off.
- [x] Root cause: `prometheus/saturation_recording_rules.yml` split the
      gauge-to-indicator adaptation across three separate rule groups
      (`saturation-indicator` -> `saturation-ratio` -> `saturation-burnrate`),
      each one's rules reading the previous group's recorded series.
      Rules in the same group evaluate sequentially in listed order, but
      Prometheus gives no ordering guarantee *between* groups - so the
      downstream group can occasionally evaluate before the upstream
      group's write for that cycle is visible, reading a one-cycle-stale
      value. For the smooth rate()-based availability/latency ratios this
      is invisible (one stale sample among many barely moves a rate());
      for the saturation fast tier's tight repeating boundary pattern it
      was enough to occasionally miss the window needed to hold `for: 2m`.
- [x] Fix: collapsed all three groups into one
      (`sample-service.slo.saturation-burnrate`), keeping the indicator /
      ratio / burn-rate rules in the same dependency order they already
      had - rules within a single group are guaranteed sequential, so each
      rule now always sees the current cycle's value from every rule
      before it. Also pinned that group's (and the saturation alerting
      group's) `interval:` to 15s, matching `prometheus/prometheus.yml`'s
      real `scrape_interval`/`evaluation_interval`, so the indicator's
      resolution doesn't depend on whatever global interval a caller (such
      as a promtool unit-test file) happens to set.
- [x] Verified the fix, not just the theory: looped the same promtool
      invocation against the fixed rule files 70 times total (two separate
      runs of 30 and 40) with zero failures, versus the reproducible ~20-30%
      failure rate beforehand. Ran the full pytest suite three times in a
      row (182 passed, 2 skipped each time) and the real `make check` /
      `make lint` / `RUN_INTEGRATION=1 pytest tests/integration` against a
      live `docker compose` stack - all passed.

### Phase 6 - Seasonal synthetic traffic (done)

- [x] `sample-service/app.py`: request *volume* now follows a sine wave
      (`seasonal_multiplier()`) on top of the configured base rate
      (`TRAFFIC_RPS`), controlled by two new startup-only env vars -
      `SEASONAL_AMPLITUDE` (default `0.5`, i.e. +/-50%) and
      `SEASONAL_PERIOD_SECONDS` (default `900`). This addresses the gap
      noted in the previous session's resume point: the request/error-rate
      Grafana panel and README screenshots looked like a flat line before
      an incident was simulated. The wave only scales how often synthetic
      requests are generated - it never touches the error/slow/queue-depth
      ratios the SLOs are evaluated against, so alert correctness and
      timing are unaffected; `GET /` still reports the unscaled base
      `traffic_rps` (unchanged, so the existing unit test asserting that
      field against the module's base-rate variable still holds) alongside
      a new `seasonal_multiplier` field for visibility.
- [x] README: new "Configuration" section documenting all six
      `sample-service` env vars (`ERROR_RATE`, `SLOW_RATE`,
      `QUEUE_DEPTH_TARGET`, `TRAFFIC_RPS`, `SEASONAL_AMPLITUDE`,
      `SEASONAL_PERIOD_SECONDS`), and a one-line mention of the wave in the
      quick start's service bullet and the repository layout.
- [x] No dashboard changes needed - `grafana/dashboards/slo-burn-rate.json`'s
      "Request Rate vs Error Rate" panel already queries
      `rate(http_requests_total[5m])`, so it picks up the new wave shape
      automatically.
- [x] Ran the real thing, not just unit tests: `make lint` clean; full
      pytest suite (186 passed, 2 skipped - the 2 skips are the
      Docker-gated integration tests); re-verified the saturation promtool
      rule unit tests are still stable under the fix from the prior session
      (5/5 consecutive runs, matching mount/invocation from
      `tests/promtool/test_promtool.py`); brought up the real
      `docker-compose` stack and confirmed `GET /` returns a live,
      changing `seasonal_multiplier`; ran
      `RUN_INTEGRATION=1 pytest tests/integration -m integration -v`
      against that real stack - both the availability and saturation
      fast-tier alerts still reached `firing` and routed to `page`
      (340.93s, 2 passed), confirming the traffic wave doesn't disrupt
      real alert timing.

### Phase 7 - Gate the slow integration-test CI job off every PR (done)

- [x] `.github/workflows/ci.yml`: added `workflow_dispatch:` to the
      workflow-level triggers and an `if:` condition on the
      `integration-test` job so it only runs automatically on pushes to
      `main`, or on demand via GitHub Actions' "Run workflow" button -
      exactly the two options the previous session's resume point left
      open. Every pull request still runs the fast
      `validate-prometheus-config` / `validate-alertmanager-config` /
      `lint-sample-service` / `test-sample-service` jobs; only the
      several-minutes Docker-compose job (which waits for a real
      burn-rate window to clear its threshold) is skipped on PRs now.
- [x] README's Status section updated to describe the new trigger
      behavior.
- [x] Verified the YAML directly: parsed `ci.yml` with the same
      `yaml.safe_load` approach `tests/config/test_ci_integration_job.py`
      uses and confirmed `workflow_dispatch` is a top-level trigger and
      the `integration-test` job's `if:` is the expected
      `github.event_name == 'workflow_dispatch' || (github.event_name ==
      'push' && github.ref == 'refs/heads/main')`. GitHub's own trigger
      evaluation isn't reproducible locally, but this confirms the YAML
      that drives it is well-formed and says what it's meant to say.
- [x] Ran the real thing: re-ran `RUN_INTEGRATION=1 pytest
      tests/integration -m integration -v` against a live `docker compose`
      stack directly - this exercises exactly the job's actual steps
      (unaffected by the trigger change, which only decides *whether*
      GitHub runs the job, not what it does) - both tests passed (340.62s),
      each fast-tier alert reaching `firing` and routing to `page`.
- [x] Full pytest suite (202 passed, 2 skipped), `make check`, and `make
      lint` all pass after the YAML change.

### Phase 8 - Final wrap-up (done)

- [x] Re-verified the full test suite from a clean virtualenv (not reusing
      any previously-installed environment): `pip install -r
      sample-service/requirements.txt -r sample-service/requirements-dev.txt
      pytest requests`, then `pytest -q` - **215 passed, 2 skipped** (the 2
      skips are the Docker-gated integration tests, run separately below).
      `ruff check sample-service/` and `make check`
      (promtool config + rules, amtool check-config) all pass.
- [x] Ran the real headline feature end to end again, not just unit tests:
      `RUN_INTEGRATION=1 pytest tests/integration -m integration -v`
      against a live `docker compose` stack - both the availability and
      saturation fast-tier alerts reached `firing` and routed to `page` in
      Alertmanager (2 passed in 330s), then tore the stack down cleanly.
- [x] Resolved the previously-noted gap below: confirmed `origin/main` on
      the published GitHub repo now points at the exact same commit as
      this branch's tip (`git rev-list --count origin/main..HEAD` is `0`),
      so the "published repo is stale" gap from the 2026-11-15 note no
      longer applies - the pipeline has since merged the prior nightly
      PRs into `main`. No push was needed or performed this session.
- [x] Spot-checked the preview screenshots in `docs/screenshots/` by
      opening them as images again - all 12 still render the real
      Prometheus/Alertmanager/Grafana UIs with populated data, no
      blank/broken panels.

## Resume point

All eight phases are complete. The full test suite passes (215 passed, 2
skipped by default; both skipped integration tests pass when run live
against a real Docker stack), `make check` and `make lint` pass, and the
published GitHub repo's `main` branch matches this branch's tip. Nothing
is broken; no further work is required for the project as scoped. This
was the project's final allocated session.

STATUS: COMPLETE
