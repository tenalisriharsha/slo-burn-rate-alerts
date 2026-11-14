# Progress

## Vision

A reference implementation of Google SRE-style multi-window multi-burn-rate
alerting: Prometheus recording rules and Alertmanager routes for a sample
service's error budget, with a runbook explaining the math and
false-positive tradeoffs.

## Architecture

```
sample-service (Flask + prometheus_client)
    - exposes /metrics (http_requests_total{code})
    - POST /error-rate lets a demo script simulate an incident
        |
        v
Prometheus
    - scrapes sample-service
    - recording_rules.yml: error ratio + burn rate over 7 windows
      (5m, 30m, 1h, 2h, 6h, 1d, 3d)
    - alerting_rules.yml: 4 multi-window multi-burn-rate alert tiers
        |              \
        v               v
Alertmanager          Grafana
    - routes severity=critical       - provisioned dashboard: burn rate
      -> "page" receiver               per window, error-budget gauge,
    - routes severity=warning          request/error rate, live alerts
      -> "ticket" receiver
    - inhibits slower tiers once a
      faster tier is already firing
```

Everything is wired together with `docker-compose.yml` so the whole stack
(including synthetic traffic) runs with one command - see the README quick
start. `scripts/demo-incident.sh` (`make demo`) scripts the manual
`make burn` / `make reset` workflow into a single ramp/hold/recover run.

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

### Phase 3 - Polish (not started)

- [ ] Second SLO profile example (latency-based, e.g. p99 < 300ms) to show
      the recording-rule pattern generalizes beyond error-rate SLOs
- [ ] Architecture diagram image for the README
- [ ] CI: add promtool rule unit tests to the pipeline, add lint for the
      sample service
- [ ] Final documentation pass

## Resume point

Start Phase 3 with the latency SLO example: it needs the sample service to
actually emit a request-duration histogram with controllable tail latency
(`app.py` currently has no artificial latency anywhere - the error-rate
control doesn't touch timing), so that part is real application code, not
just orchestration. Plan:

1. `sample-service/app.py`: add a `http_request_duration_seconds` Histogram,
   and a second runtime-adjustable knob (e.g. `/slow-rate`, mirroring
   `/error-rate`) that controls what fraction of synthetic requests sleep
   for ~400ms instead of completing instantly.
2. `prometheus/latency_recording_rules.yml` +
   `prometheus/latency_alerting_rules.yml`: same burn-rate pattern as the
   error-budget rules, but for a `p99 < 300ms` SLO - add both to
   `prometheus.yml`'s `rule_files`. Give the alerts a distinct
   `slo: sample-service-latency` label so they route through the existing
   severity-based Alertmanager rules without any changes there.
3. Add a panel (or a second dashboard) in `grafana/dashboards/` for the
   latency burn rate.
4. Extend `docs/runbook.md` with a short section making the "the thresholds
   only depend on the error budget, not the metric" point explicit by
   showing the same math applied to latency.
5. Then: architecture diagram image, CI promtool-rule-unit-test step, a
   final documentation pass - all smaller, do them after the latency
   example works end-to-end against the real stack.

STATUS: IN_PROGRESS
