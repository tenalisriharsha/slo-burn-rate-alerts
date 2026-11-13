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

## Tuning for your own service

The constants that are specific to *this* SLO (not to the method) live in
one place: the `0.001` divisor in
[`prometheus/recording_rules.yml`](../prometheus/recording_rules.yml), which
is `1 - target_availability`. Changing the SLO target means changing that
one number; the burn-rate thresholds (14.4, 6, 3, 1) stay the same regardless
of what the SLO target is, because they're expressed in multiples of
whatever the budget is - that's the whole point of the burn-rate
abstraction.
