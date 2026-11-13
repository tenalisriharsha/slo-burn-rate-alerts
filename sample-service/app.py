"""Sample service used to demonstrate SLO burn-rate alerting.

Exposes a Prometheus /metrics endpoint with an http_requests_total counter,
and continuously generates synthetic traffic at a configurable error rate so
the burn-rate recording rules and alerts in ../prometheus have something
real to evaluate. The error rate can be changed at runtime via /error-rate
to simulate an incident without restarting anything.
"""
import os
import random
import threading
import time

from flask import Flask, jsonify, request
from prometheus_client import CONTENT_TYPE_LATEST, Counter, generate_latest

app = Flask(__name__)

REQUEST_COUNTER = Counter(
    "http_requests_total",
    "Total synthetic HTTP requests handled by the sample service",
    ["method", "code"],
)

_state_lock = threading.Lock()
_error_rate = float(os.environ.get("ERROR_RATE", "0.001"))
_traffic_rps = float(os.environ.get("TRAFFIC_RPS", "20"))


def get_error_rate() -> float:
    with _state_lock:
        return _error_rate


def set_error_rate(rate: float) -> float:
    rate = max(0.0, min(1.0, rate))
    with _state_lock:
        global _error_rate
        _error_rate = rate
    return rate


def _traffic_loop() -> None:
    while True:
        rate = get_error_rate()
        is_error = random.random() < rate
        REQUEST_COUNTER.labels(method="GET", code="500" if is_error else "200").inc()
        time.sleep(1.0 / max(_traffic_rps, 0.1))


@app.get("/")
def index():
    return jsonify(
        service="sample-service",
        error_rate=get_error_rate(),
        traffic_rps=_traffic_rps,
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


def main() -> None:
    thread = threading.Thread(target=_traffic_loop, daemon=True)
    thread.start()
    app.run(host="0.0.0.0", port=8000)


if __name__ == "__main__":
    main()
