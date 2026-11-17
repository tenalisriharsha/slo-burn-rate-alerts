# Daily Report: slo-burn-rate-alerts

Summary of what was built across all sessions on this project. See
[PROGRESS.md](PROGRESS.md) for the detailed phase-by-phase checklist and
[README.md](README.md) for user-facing documentation.

## What was built

A reference implementation of Google SRE-style multi-window, multi-burn-rate
SLO alerting, covering three independent SLOs on the same sample service:

- **Availability** - 99.9% success rate over 30 days (0.1% error budget)
- **Latency** - 99% of requests under 300ms over 30 days (1% error budget)
- **Saturation** - queue depth under 50 items 98% of the time over 30 days
  (2% error budget) - the odd one out, since it's measured on a gauge
  rather than a good/bad event ratio

All three SLOs share one implementation pattern end to end:

1. **sample-service** (Flask + `prometheus_client`) exposes `/metrics` with
   an `http_requests_total` counter, an `http_request_duration_seconds`
   histogram, and a `sample_service_queue_depth` gauge, plus
   `POST /error-rate`, `POST /slow-rate`, and `POST /queue-depth` to
   simulate an incident at runtime without restarting anything.
2. **Prometheus** recording rules compute the error/latency/saturation
   ratio and the burn rate (ratio divided by the error budget) over seven
   windows (5m, 30m, 1h, 2h, 6h, 1d, 3d) per SLO. The saturation ratio
   needs one extra step first, since it starts from a gauge: a recording
   rule turns the gauge into a `1`/`0` over-threshold indicator, which
   `avg_over_time()` can then reduce to the same "fraction of time bad"
   ratio shape the other two SLOs get directly from `rate()`.
3. **Prometheus** alerting rules define four tiers per SLO - fast,
   medium-fast, slow, very-slow - each requiring a short window AND a long
   window to simultaneously exceed the same burn-rate threshold (14.4x, 6x,
   3x, 1x) before firing, per the Google SRE Workbook's method.
4. **Alertmanager** routes purely on the `severity` label (critical ->
   page, warning -> ticket), so all three SLOs route through identical
   rules with zero SLO-specific configuration, and inhibits slower tiers
   once a faster tier for the same SLO is already firing.
5. **Grafana** auto-provisions a dashboard (datasource + dashboard JSON,
   no manual clicking) visualizing burn rate per window for all three
   SLOs, an error-budget-exhaustion gauge, a p99 latency estimate, queue
   depth vs its saturation threshold, request/error rate, and live alert
   tables.

Supporting pieces: `docker-compose.yml` wires all four services together
behind `make up`; `scripts/demo-incident.sh` (`make demo`) scripts a
ramp/hold/recover incident; `docs/runbook.md` explains the burn-rate math,
the multi-window rationale, the false-positive/false-negative tradeoffs,
and the gauge-to-ratio adaptation the saturation SLO needs;
`docs/integrations.md` documents wiring up real PagerDuty/Slack delivery
(the receiver blocks ship commented out with `${VAR}` placeholders, not
real credentials).

## Test results

Full suite: **164 passed, 2 skipped** by default (the skips are
`tests/integration/test_stack.py`'s two tests, gated on
`RUN_INTEGRATION=1` - run explicitly, both passed against a live stack,
each fast-tier alert reaching `firing` and routing to `page` in
Alertmanager in under 6 minutes). Coverage spans:

- `tests/unit/` - sample-service Flask routes and state
- `tests/config/` - structural checks on the Prometheus/Alertmanager/
  Grafana config files
- `tests/promtool/` - real `promtool`/`amtool` validation and alert-tier
  boundary unit tests, run via Docker
- `tests/integration/` - brings up the real `docker-compose` stack and
  asserts against it

CI (`.github/workflows/ci.yml`) runs config validation, linting, and the
test suite on every push/PR, plus a dedicated `integration-test` job that
runs the Docker-gated end-to-end test against the real stack rather than
only validating its YAML. The config-validation jobs were fixed earlier -
see below.

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
- The saturation SLO's indicator (`sample_service:queue_saturated:bool`)
  is only as fine-grained as Prometheus's `evaluation_interval` (15s
  here), so a saturation spike shorter than that window can be averaged
  away entirely - a real cost of the gauge-to-ratio adaptation, unlike the
  counter-based availability and latency SLOs, which see every request.

## Future ideas

See the "Resume point" section of [PROGRESS.md](PROGRESS.md) for a short
list of possible follow-ups (more realistic synthetic traffic patterns;
possibly gating the `integration-test` CI job to `push`/`workflow_dispatch`
if its several-minutes runtime becomes annoying on every PR). None are
required - the project as scoped is complete.
