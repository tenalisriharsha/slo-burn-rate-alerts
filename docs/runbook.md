# Runbook: SLO Burn-Rate Alerts

This runbook explains the math behind the alerts in this repository, how to
respond to each one, and the tradeoffs involved in choosing the thresholds.
It assumes the reader is on-call and has just been paged, or is reviewing
the alerting design.

## The SLO

`sample-service` has an availability objective of **99.9% over a rolling
30-day window**, measured as the fraction of HTTP requests that do *not*
return a 5xx status code.

That gives an **error budget** of `1 - 0.999 = 0.001` (0.1%): the fraction of
requests that are allowed to fail over 30 days before the SLO is breached.

## What "burn rate" means

Burn rate is the error ratio observed right now, expressed as a multiple of
the rate the error budget is *designed* to be spent at:

```
burn_rate = error_ratio / error_budget
```

- `burn_rate == 1` means the service is failing requests at exactly the rate
  that would consume the entire 30-day budget in exactly 30 days.
- `burn_rate == 14.4` means the service is failing 14.4x too fast - at that
  rate the 30-day budget would be gone in `30 / 14.4 ≈ 2.08` days.

This repo computes `error_ratio` and `burn_rate` for seven windows (5m, 30m,
1h, 2h, 6h, 1d, 3d) as Prometheus recording rules in
[`prometheus/recording_rules.yml`](../prometheus/recording_rules.yml), so the
alerting rules themselves are just threshold comparisons on pre-computed
series instead of re-running `rate()` expressions under alert evaluation
pressure.

## Why multi-window AND multi-burn-rate

A single burn-rate alert on one window is a lossy tradeoff:

- A **short window** (e.g. 5m) reacts fast but is noisy - a brief blip (a bad
  deploy that gets rolled back in 90 seconds, a single downstream timeout)
  pushes the ratio over threshold and pages someone for a non-event. It also
  *resolves* fast, so a real short outage can clear before anyone looks at it.
- A **long window** (e.g. 1h) is stable and hard to false-positive on, but it
  is slow both to fire (a real incident takes a long time to move a 1h
  average) and slow to resolve (it keeps alerting long after the incident is
  actually fixed, because the bad minutes are still inside the window).

Google's SRE Workbook (ch. 5, "Alerting on SLOs") addresses this by requiring
**both** a long window and a short window to simultaneously exceed the same
burn-rate threshold before firing. The long window gives confidence that this
isn't just noise; the short window means the alert clears quickly once the
real problem is actually fixed, instead of lingering for a full long-window
duration. That's the `and` in every alert expression in
[`prometheus/alerting_rules.yml`](../prometheus/alerting_rules.yml).

Four tiers then cover the speed/confidence spectrum from "page immediately"
to "file a ticket, nobody's night needs to be ruined":

| Alert | Long window | Short window | Threshold | `for` | Budget burned by the time it's actionable | Severity |
|---|---|---|---|---|---|---|
| `SampleServiceErrorBudgetBurnFast` | 1h | 5m | 14.4x | 2m | ~2% | critical (page) |
| `SampleServiceErrorBudgetBurnMediumFast` | 6h | 30m | 6x | 15m | ~5% | critical (page) |
| `SampleServiceErrorBudgetBurnSlow` | 1d | 2h | 3x | 1h | ~10% | warning (ticket) |
| `SampleServiceErrorBudgetBurnVerySlow` | 3d | 6h | 1x | 3h | ~10% | warning (ticket) |

These are the standard thresholds from the Google SRE Workbook's 99.9%
availability example, carried through unchanged because the math only
depends on the SLO's error budget, not on what the service does.

### Fast burn (page)

Full budget exhausted in **~2 days** if the rate holds. This is almost always
a real, severe incident (a bad deploy, a dependency outage, a config error) -
page immediately and start incident response. Check recent deploys first.

### Medium-fast burn (page)

Full budget exhausted in **~5 days**. Same response as fast burn, just a
notch less urgent - still real, still worth an immediate page, but the window
being longer (30m) means it's already survived more scrutiny before firing.

### Slow burn (ticket)

Full budget exhausted in **~10 days**. Usually not a single incident but a
sustained elevated error rate - a flaky dependency, a slow memory leak
causing periodic restarts, a regression that shipped a few days ago and
hasn't been caught. File a ticket and investigate during business hours;
no need to wake anyone up.

### Very slow burn (ticket)

Tracking to exhaust the entire 30-day budget by the end of the period. This
is the "the SLO itself is at risk this month" signal - useful for a
retrospective conversation about reliability investment, not an emergency.

## False positives vs false negatives

Every choice here is a tradeoff on the same two axes:

- **Precision** (how often a firing alert turns out to not matter) is
  improved by longer windows and higher `for` durations - more confirmation
  before paging.
- **Time to detect** is hurt by exactly those same two settings.

The four-tier design resolves this by not picking one tradeoff: fast,
noisier detection is allowed for high-burn-rate (severe) events, where the
cost of a few seconds of extra noise is worth catching real incidents in
minutes; and for low-burn-rate (mild, chronic) events, the design accepts
slower detection because burning the budget over 5-10+ days gives plenty of
time to react, and raising the bar avoids paging anyone for noise.

[`alertmanager/alertmanager.yml`](../alertmanager/alertmanager.yml) also
inhibits slower tiers once a faster tier for the same SLO is already firing,
so a severe incident doesn't also generate a redundant ticket.

## Latency SLO

`sample-service` also carries a second, independent SLO: **99% of requests
complete in under 300ms, over a rolling 30-day window** (a p99 latency
target). This section exists to make the point from the previous sections
concrete: the multi-window multi-burn-rate *method* only depends on the
error budget, not on what's being measured.

The error budget here is `1 - 0.99 = 0.01` (1%): the fraction of requests
that are allowed to take 300ms or longer before the SLO is breached. That
budget constant is the only thing that changes from the availability SLO
above (`0.001` there vs `0.01` here) - everything else is the identical
shape:

- `sample_service:requests_fast:rate<window>` in
  [`prometheus/latency_recording_rules.yml`](../prometheus/latency_recording_rules.yml)
  reads the cumulative `le="0.3"` bucket of the
  `http_request_duration_seconds` histogram exposed by the sample service,
  giving the rate of "good" (fast enough) requests - the latency
  equivalent of `sample_service:errors:rate<window>`, just inverted (good
  events instead of bad ones).
- `sample_service:latency_ratio:rate<window>` is
  `1 - (fast_requests / total_requests)`, i.e. the fraction of *bad*
  (too-slow) requests - exactly `sample_service:error_ratio:rate<window>`'s
  role.
- `sample_service:latency_burnrate<window>` is `latency_ratio / 0.01`, the
  same division by the error budget as the availability burn rate.

The four alert tiers in
[`prometheus/latency_alerting_rules.yml`](../prometheus/latency_alerting_rules.yml)
reuse the *exact same* thresholds (14.4x / 6x / 3x / 1x) and `for`
durations (2m / 15m / 1h / 3h) as the availability tiers, because those
numbers are a function of the error-budget abstraction, not of the SLO's
target metric. Each latency alert carries `slo: sample-service-latency`
(instead of `sample-service-availability`) and the same `severity` labels,
so it routes through the existing severity-based rules in
[`alertmanager/alertmanager.yml`](../alertmanager/alertmanager.yml) with no
changes needed there - severity, not the SLO name, decides page vs ticket.

To demo it: `POST /slow-rate` on the sample service (mirroring
`POST /error-rate`) sets the fraction of synthetic requests that take
350-600ms instead of 10-80ms, which pushes
`sample_service:latency_burnrate*` up the same way raising `/error-rate`
pushes `sample_service:burnrate*` up.

## Saturation SLO

`sample-service` also carries a third, independent SLO: a **queue depth
under 50 items at least 98% of the time**, over a rolling 30-day window -
a saturation objective, standing in for any resource-utilization signal
(queue depth, worker-pool occupancy, connection-pool usage, disk headroom,
...) a real service might track. Unlike the two SLOs above, this one is
not a good/bad event ratio: `sample_service_queue_depth` is a **gauge**,
not a counter, so there's no `rate(bad_events) / rate(total_events)` to
take in the first place.

[`prometheus/saturation_recording_rules.yml`](../prometheus/saturation_recording_rules.yml)
bridges that gap in two steps:

1. `sample_service:queue_saturated:bool` records
   `sample_service_queue_depth > bool 50` on every evaluation. The `> bool`
   operator turns the comparison into a `1`/`0` value instead of filtering
   the series away, which - critically - makes this itself a regular time
   series in Prometheus's storage, sampled once per `evaluation_interval`.
2. `sample_service:saturation_ratio:rate<window>` then takes
   `avg_over_time()` of that `1`/`0` series over each of the same seven
   windows used by the other two SLOs. Averaging a `1`/`0` series over a
   window *is* "fraction of time spent in that state" - the same ratio
   shape as `error_ratio` and `latency_ratio`, just built from
   `avg_over_time()` on a derived indicator instead of `rate()` on a raw
   counter.

From there, nothing changes: `sample_service:saturation_burnrate<window>`
divides by the error budget (`1 - 0.98 = 0.02`) exactly like the other two
SLOs, and
[`prometheus/saturation_alerting_rules.yml`](../prometheus/saturation_alerting_rules.yml)
reuses the identical four thresholds and `for` durations, with
`slo: sample-service-saturation` routing through the same severity-based
Alertmanager rules with no changes needed there.

This is the point the previous two SLOs couldn't make on their own: the
multi-window multi-burn-rate *method* generalizes to any metric that can be
reduced to "fraction of time/requests in a bad state" - which covers far
more than simple event ratios - but gauge-shaped signals need that one
extra recording-rule step to get there. The adaptation does cost something:
the indicator is only as fine-grained as `evaluation_interval` (15s here),
so a saturation spike shorter than that can be averaged away entirely,
whereas the counter-based SLOs capture every single request regardless of
how briefly it was bad.

To demo it: `POST /queue-depth` on the sample service (mirroring
`POST /error-rate` and `POST /slow-rate`) sets the target queue depth the
synthetic traffic loop jitters around, which pushes
`sample_service:saturation_burnrate*` up the same way raising
`/error-rate` or `/slow-rate` pushes the other two burn rates up.

## Tuning for your own service

For each SLO, the constant that's specific to *that* SLO (not to the
method) lives in one place: the `0.001` divisor in
[`prometheus/recording_rules.yml`](../prometheus/recording_rules.yml) for
availability, the `0.01` divisor in
[`prometheus/latency_recording_rules.yml`](../prometheus/latency_recording_rules.yml)
for latency, or the `0.02` divisor and the `50`-item threshold in
[`prometheus/saturation_recording_rules.yml`](../prometheus/saturation_recording_rules.yml)
for saturation - the budget divisors are all `1 - target`. Changing an
SLO's target means changing that one number (plus the threshold constant
for a gauge-based SLO like saturation); the burn-rate thresholds (14.4, 6,
3, 1) stay the same regardless of what the target is, because they're
expressed in multiples of whatever the budget is - that's the whole point
of the burn-rate abstraction, and exactly why the latency and saturation
SLOs above could both reuse the same four tiers unchanged.
