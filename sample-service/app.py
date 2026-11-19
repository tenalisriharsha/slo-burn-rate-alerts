"""Sample service used to demonstrate SLO burn-rate alerting.

Exposes a Prometheus /metrics endpoint with an http_requests_total counter,
an http_request_duration_seconds histogram, and a sample_service_queue_depth
gauge, and continuously generates synthetic traffic at a configurable error
rate, slow-request rate, and queue depth so the burn-rate recording rules
and alerts in ../prometheus have something real to evaluate. All three
knobs can be changed at runtime - via /error-rate, /slow-rate, and
/queue-depth respectively - to simulate an incident without restarting
anything.

Request *volume* (as opposed to the error/slow/queue-depth ratios above)
follows a sine-wave "seasonality" on top of the configured base rate
(TRAFFIC_RPS), so the request/error-rate panels in the Grafana dashboard
and README screenshots show a rising-and-falling wave rather than a flat
line even with no incident in progress - closer to what a real service's
traffic looks like. This only scales how often synthetic requests are
recorded; it never changes the error/slow/saturation ratios the SLOs are
evaluated against, so it has no effect on alert correctness or timing.
"""
import math
import os
import random
import threading
import time

from flask import Flask, jsonify, request
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Gauge, Histogram, generate_latest

app = Flask(__name__)

REQUEST_COUNTER = Counter(
    "http_requests_total",
    "Total synthetic HTTP requests handled by the sample service",
    ["method", "code"],
)

# Buckets include 0.3 exactly so the latency SLO (p99 < 300ms) can be
# evaluated as the fraction of requests in the le="0.3" cumulative bucket,
# the same "good events / total events" shape as the error-rate SLO - see
# prometheus/latency_recording_rules.yml.
LATENCY_HISTOGRAM = Histogram(
    "http_request_duration_seconds",
    "Synthetic HTTP request duration in seconds",
    buckets=(0.01, 0.05, 0.1, 0.2, 0.3, 0.5, 1.0, 2.0, 5.0),
)

# Saturation SLO demo metric: a gauge, not a counter - standing in for any
# saturation signal (queue depth, worker-pool utilization, connection-pool
# usage, ...) that isn't shaped as a good/bad event ratio like the two
# metrics above. See prometheus/saturation_recording_rules.yml for how a
# gauge gets turned into the same burn-rate shape as the other two SLOs.
QUEUE_DEPTH_GAUGE = Gauge(
    "sample_service_queue_depth",
    "Synthetic count of items waiting in the service's work queue",
)

_state_lock = threading.Lock()
_error_rate = float(os.environ.get("ERROR_RATE", "0.001"))
_slow_rate = float(os.environ.get("SLOW_RATE", "0.001"))
_queue_depth_target = float(os.environ.get("QUEUE_DEPTH_TARGET", "5"))
_traffic_rps = float(os.environ.get("TRAFFIC_RPS", "20"))

# Seasonality is a wave on top of _traffic_rps, not a replacement for it:
# amplitude is clamped to [0, 0.95] so the effective rate can never reach
# zero, and _traffic_rps itself (reported by GET /) always stays the
# configured base rate, independent of what phase of the wave traffic is
# currently in.
_seasonal_amplitude = max(0.0, min(0.95, float(os.environ.get("SEASONAL_AMPLITUDE", "0.5"))))
_seasonal_period_seconds = max(1.0, float(os.environ.get("SEASONAL_PERIOD_SECONDS", "900")))


def seasonal_multiplier(now: float) -> float:
    """Return the sine-wave traffic multiplier for wall-clock time `now`
    (seconds, e.g. time.time()). Always in
    [1 - _seasonal_amplitude, 1 + _seasonal_amplitude], so multiplying
    _traffic_rps by this never drives the effective rate to zero or
    negative.
    """
    return 1.0 + _seasonal_amplitude * math.sin(2 * math.pi * now / _seasonal_period_seconds)


def get_error_rate() -> float:
    with _state_lock:
        return _error_rate


def set_error_rate(rate: float) -> float:
    rate = max(0.0, min(1.0, rate))
    with _state_lock:
        global _error_rate
        _error_rate = rate
    return rate


def get_slow_rate() -> float:
    with _state_lock:
        return _slow_rate


def set_slow_rate(rate: float) -> float:
    rate = max(0.0, min(1.0, rate))
    with _state_lock:
        global _slow_rate
        _slow_rate = rate
    return rate


def get_queue_depth_target() -> float:
    with _state_lock:
        return _queue_depth_target


def set_queue_depth_target(target: float) -> float:
    target = max(0.0, min(500.0, target))
    with _state_lock:
        global _queue_depth_target
        _queue_depth_target = target
    return target


def _traffic_loop() -> None:
    while True:
        is_error = random.random() < get_error_rate()
        REQUEST_COUNTER.labels(method="GET", code="500" if is_error else "200").inc()

        is_slow = random.random() < get_slow_rate()
        duration = random.uniform(0.35, 0.6) if is_slow else random.uniform(0.01, 0.08)
        LATENCY_HISTOGRAM.observe(duration)

        depth = max(0.0, get_queue_depth_target() + random.uniform(-3.0, 3.0))
        QUEUE_DEPTH_GAUGE.set(depth)

        effective_rps = max(_traffic_rps * seasonal_multiplier(time.time()), 0.1)
        time.sleep(1.0 / effective_rps)


@app.get("/")
def index():
    return jsonify(
        service="sample-service",
        error_rate=get_error_rate(),
        slow_rate=get_slow_rate(),
        queue_depth_target=get_queue_depth_target(),
        traffic_rps=_traffic_rps,
        seasonal_multiplier=seasonal_multiplier(time.time()),
    )


@app.get("/metrics")
def metrics():
    return generate_latest(), 200, {"Content-Type": CONTENT_TYPE_LATEST}


@app.get("/error-rate")
def get_error_rate_route():
    return jsonify(error_rate=get_error_rate())


@app.post("/error-rate")
def set_error_rate_route():
    payload = request.get_json(silent=True) or {}
    if "rate" not in payload:
        return jsonify(error="missing 'rate' field in request body"), 400
    try:
        rate = float(payload["rate"])
    except (TypeError, ValueError):
        return jsonify(error="'rate' must be a number between 0 and 1"), 400
    applied = set_error_rate(rate)
    return jsonify(error_rate=applied)


@app.get("/slow-rate")
def get_slow_rate_route():
    return jsonify(slow_rate=get_slow_rate())


@app.post("/slow-rate")
def set_slow_rate_route():
    payload = request.get_json(silent=True) or {}
    if "rate" not in payload:
        return jsonify(error="missing 'rate' field in request body"), 400
    try:
        rate = float(payload["rate"])
    except (TypeError, ValueError):
        return jsonify(error="'rate' must be a number between 0 and 1"), 400
    applied = set_slow_rate(rate)
    return jsonify(slow_rate=applied)


@app.get("/queue-depth")
def get_queue_depth_route():
    return jsonify(queue_depth_target=get_queue_depth_target())


@app.post("/queue-depth")
def set_queue_depth_route():
    payload = request.get_json(silent=True) or {}
    if "target" not in payload:
        return jsonify(error="missing 'target' field in request body"), 400
    try:
        target = float(payload["target"])
    except (TypeError, ValueError):
        return jsonify(error="'target' must be a number between 0 and 500"), 400
    applied = set_queue_depth_target(target)
    return jsonify(queue_depth_target=applied)


def main() -> None:
    thread = threading.Thread(target=_traffic_loop, daemon=True)
    thread.start()
    app.run(host="0.0.0.0", port=8000)


if __name__ == "__main__":
    main()
