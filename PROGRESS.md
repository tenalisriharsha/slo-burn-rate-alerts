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
        |
        v
Alertmanager
    - routes severity=critical -> "page" receiver
    - routes severity=warning  -> "ticket" receiver
    - inhibits slower tiers once a faster tier is already firing
```

Everything is wired together with `docker-compose.yml` so the whole stack
(including synthetic traffic) runs with one command - see the README quick
start.

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

### Phase 2 - Visualization + routing depth (not started)

- [ ] Grafana dashboard (burn rate per tier, error budget remaining gauge,
      request/error rate panels), provisioned via docker-compose
- [ ] `scripts/` demo script that drives `/error-rate` through a scripted
      incident (ramp up, hold, recover) so each alert tier can be
      demonstrated end-to-end on demand
- [ ] Alertmanager receiver templates with real integration instructions
      (Slack, PagerDuty) rather than placeholders
- [ ] promtool rule unit tests (fixtures owned by the test suite, not this
      phase) covering each alert tier's threshold boundaries

### Phase 3 - Polish (not started)

- [ ] Second SLO profile example (latency-based, e.g. p99 < 300ms) to show
      the recording-rule pattern generalizes beyond error-rate SLOs
- [ ] Architecture diagram image for the README
- [ ] CI: add promtool rule unit tests to the pipeline, add lint for the
      sample service
- [ ] Final documentation pass

## Resume point

Start Phase 2 by writing `docker-compose.yml`'s Grafana service (image
`grafana/grafana`, provisioned datasource pointing at `prometheus:9090`) and
a dashboard JSON under `grafana/dashboards/` with panels for
`sample_service:burnrate5m/1h/6h/1d`. Then write
`scripts/demo-incident.sh`, which should call the sample service's existing
`POST /error-rate` endpoint (see `sample-service/app.py`) - no new
application code needed, just orchestration.

STATUS: IN_PROGRESS
