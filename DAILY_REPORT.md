# Daily Report: slo-burn-rate-alerts

Summary of what was built across all sessions on this project. See
[PROGRESS.md](PROGRESS.md) for the detailed phase-by-phase checklist and
[README.md](README.md) for user-facing documentation.

## What was built

A reference implementation of Google SRE-style multi-window, multi-burn-rate
SLO alerting, covering two independent SLOs on the same sample service:

- **Availability** - 99.9% success rate over 30 days (0.1% error budget)
- **Latency** - 99% of requests under 300ms over 30 days (1% error budget)

Both SLOs share one implementation pattern end to end:

1. **sample-service** (Flask + `prometheus_client`) exposes `/metrics` with
   an `http_requests_total` counter and an `http_request_duration_seconds`
   histogram, plus `POST /error-rate` and `POST /slow-rate` to simulate an
   incident at runtime without restarting anything.
2. **Prometheus** recording rules compute the error/latency ratio and the
   burn rate (ratio divided by the error budget) over seven windows (5m,
   30m, 1h, 2h, 6h, 1d, 3d) per SLO.
3. **Prometheus** alerting rules define four tiers per SLO - fast,
   medium-fast, slow, very-slow - each requiring a short window AND a long
   window to simultaneously exceed the same burn-rate threshold (14.4x, 6x,
   3x, 1x) before firing, per the Google SRE Workbook's method.
4. **Alertmanager** routes purely on the `severity` label (critical ->
   page, warning -> ticket), so both SLOs route through identical rules
   with zero SLO-specific configuration, and inhibits slower tiers once a
   faster tier for the same SLO is already firing.
5. **Grafana** auto-provisions a dashboard (datasource + dashboard JSON,
   no manual clicking) visualizing burn rate per window for both SLOs, an
   error-budget-exhaustion gauge, a p99 latency estimate, request/error
   rate, and live alert tables.

Supporting pieces: `docker-compose.yml` wires all four services together
behind `make up`; `scripts/demo-incident.sh` (`make demo`) scripts a
ramp/hold/recover incident; `docs/runbook.md` explains the burn-rate math,
the multi-window rationale, and the false-positive/false-negative
tradeoffs for both SLOs; `docs/integrations.md` documents wiring up real
PagerDuty/Slack delivery (the receiver blocks ship commented out with
`${VAR}` placeholders, not real credentials).

## Test results

Full suite: **65 passed, 1 skipped** (the skip is
`tests/integration/test_stack.py`, gated on Docker being available - it
passed when run against a live stack this session). Coverage spans:

- `tests/unit/` - sample-service Flask routes and state
- `tests/config/` - structural checks on the Prometheus/Alertmanager/
  Grafana config files
- `tests/promtool/` - real `promtool`/`amtool` validation and alert-tier
  boundary unit tests, run via Docker
- `tests/integration/` - brings up the real `docker-compose` stack and
  asserts against it

CI (`.github/workflows/ci.yml`) runs config validation, linting, and the
test suite on every push/PR. The config-validation jobs were fixed this
session - see below.

## What was fixed

CI was red on the first opened PR: `validate-prometheus-config` and
`validate-alertmanager-config` both failed because they ran inside
`container: prom/prometheus:latest` / `prom/alertmanager:latest`, and
`actions/checkout` (a JS action) has no Node.js runtime to run on those
minimal images. Fixed by running those jobs on the normal `ubuntu-latest`
runner and validating via `docker run` against a mounted volume instead -
the same approach `make check` already used successfully.

## Known limitations

- The sample service's synthetic traffic is flat (no daily/weekly
  seasonality), so burn-rate graphs look like a flat line until an
  incident is simulated - fine for demonstrating the alerting method, not
  representative of real traffic shape.
- The latency histogram's observed durations are synthetic values chosen
  to land on either side of the 300ms bucket boundary; the service does
  not actually sleep for that duration per request (doing so would throttle
  the configured requests-per-second), so wall-clock request latency and
  the reported histogram are intentionally decoupled, same as the
  error-rate knob doesn't actually fail real requests.
- No real PagerDuty/Slack credentials are wired up by default (by design -
  this is a public reference repo); `docs/integrations.md` covers activating
  them.
- Only two SLO shapes are demonstrated (both are good/bad-event ratios).
  A saturation-style SLO on a gauge metric would need a different
  recording-rule shape - noted as a future idea in PROGRESS.md.

## Future ideas

See the "Resume point" section of [PROGRESS.md](PROGRESS.md) for a short
list of possible follow-ups (a third, non-ratio SLO shape; a CI profile
that exercises the live stack instead of only validating config; more
realistic synthetic traffic patterns). None are required - the project as
scoped is complete.
