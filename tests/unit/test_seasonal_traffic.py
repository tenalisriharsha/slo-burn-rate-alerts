"""Unit tests for the seasonal traffic wave added to sample-service/app.py
(README's "Configuration" section and the module's own docstring/comments):

- seasonal_multiplier(now) is `1 + amplitude * sin(2*pi*now/period)`, always
  within [1 - amplitude, 1 + amplitude].
- SEASONAL_AMPLITUDE is clamped to [0, 0.95] and SEASONAL_PERIOD_SECONDS to a
  minimum of 1 second; both default to 0.5 / 900 when unset.
- The wave only scales how often synthetic requests are generated
  (_traffic_loop's sleep interval) - it never changes `traffic_rps` as
  reported by GET /, and amplitude 0 disables the wave entirely.

Uses the real app module (no mocking of the project's own code); only the
stdlib `time` module is monkeypatched to pin wall-clock time for
deterministic assertions.
"""
import importlib
import math
import os
import sys
from contextlib import contextmanager
from pathlib import Path

import pytest
from prometheus_client import REGISTRY

SAMPLE_SERVICE_DIR = Path(__file__).resolve().parents[2] / "sample-service"
sys.path.insert(0, str(SAMPLE_SERVICE_DIR))

app_module = importlib.import_module("app")

SEASONAL_ENV_VARS = ("SEASONAL_AMPLITUDE", "SEASONAL_PERIOD_SECONDS")
COLLECTOR_ATTRS = ("REQUEST_COUNTER", "LATENCY_HISTOGRAM", "QUEUE_DEPTH_GAUGE")


def _reload_app():
    for attr in COLLECTOR_ATTRS:
        collector = getattr(app_module, attr, None)
        if collector is not None:
            try:
                REGISTRY.unregister(collector)
            except KeyError:
                pass
    importlib.reload(app_module)


@contextmanager
def reloaded_with_env(**env_overrides):
    """Set SEASONAL_AMPLITUDE/SEASONAL_PERIOD_SECONDS to the given values
    (unset ones are removed, so defaults apply), reload app.py so its
    module-level globals pick up the change, yield the reloaded module,
    then restore the environment and module to their prior state.
    """
    original = {name: os.environ.get(name) for name in SEASONAL_ENV_VARS}
    try:
        for name in SEASONAL_ENV_VARS:
            if name in env_overrides:
                os.environ[name] = str(env_overrides[name])
            else:
                os.environ.pop(name, None)
        _reload_app()
        yield app_module
    finally:
        for name, value in original.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value
        _reload_app()


@pytest.fixture
def client():
    app_module.set_error_rate(0.001)
    app_module.set_slow_rate(0.001)
    app_module.set_queue_depth_target(5.0)
    return app_module.app.test_client()


def test_seasonal_env_vars_default_to_the_documented_values():
    with reloaded_with_env():
        assert app_module._seasonal_amplitude == pytest.approx(0.5)
        assert app_module._seasonal_period_seconds == pytest.approx(900.0)


def test_seasonal_multiplier_matches_the_documented_sine_formula():
    with reloaded_with_env(SEASONAL_AMPLITUDE=0.5, SEASONAL_PERIOD_SECONDS=900):
        amplitude = app_module._seasonal_amplitude
        period = app_module._seasonal_period_seconds
        for now in (0.0, 100.0, period / 4, period / 2, 3 * period / 4, period, 12345.6):
            expected = 1.0 + amplitude * math.sin(2 * math.pi * now / period)
            assert app_module.seasonal_multiplier(now) == pytest.approx(expected)


def test_seasonal_multiplier_at_t_zero_is_one():
    with reloaded_with_env(SEASONAL_AMPLITUDE=0.5, SEASONAL_PERIOD_SECONDS=900):
        assert app_module.seasonal_multiplier(0.0) == pytest.approx(1.0)


def test_seasonal_multiplier_peak_and_trough_match_the_amplitude():
    with reloaded_with_env(SEASONAL_AMPLITUDE=0.5, SEASONAL_PERIOD_SECONDS=900):
        period = app_module._seasonal_period_seconds
        peak = app_module.seasonal_multiplier(period / 4)
        trough = app_module.seasonal_multiplier(3 * period / 4)
        assert peak == pytest.approx(1.5)
        assert trough == pytest.approx(0.5)


def test_seasonal_multiplier_is_periodic():
    with reloaded_with_env(SEASONAL_AMPLITUDE=0.5, SEASONAL_PERIOD_SECONDS=900):
        period = app_module._seasonal_period_seconds
        for now in (37.0, 123.4, 800.0):
            assert app_module.seasonal_multiplier(now) == pytest.approx(
                app_module.seasonal_multiplier(now + period)
            )


def test_seasonal_multiplier_stays_within_amplitude_bounds():
    with reloaded_with_env(SEASONAL_AMPLITUDE=0.5, SEASONAL_PERIOD_SECONDS=900):
        amplitude = app_module._seasonal_amplitude
        period = app_module._seasonal_period_seconds
        for step in range(0, 37):
            now = step * (period / 37.0)
            multiplier = app_module.seasonal_multiplier(now)
            assert 1.0 - amplitude - 1e-9 <= multiplier <= 1.0 + amplitude + 1e-9


def test_seasonal_amplitude_zero_disables_the_wave():
    with reloaded_with_env(SEASONAL_AMPLITUDE=0, SEASONAL_PERIOD_SECONDS=900):
        assert app_module._seasonal_amplitude == pytest.approx(0.0)
        for now in (0.0, 50.0, 225.0, 450.0, 675.0, 900.0):
            assert app_module.seasonal_multiplier(now) == pytest.approx(1.0)


def test_seasonal_amplitude_above_one_is_clamped_to_0_95():
    with reloaded_with_env(SEASONAL_AMPLITUDE=5.0, SEASONAL_PERIOD_SECONDS=900):
        assert app_module._seasonal_amplitude == pytest.approx(0.95)


def test_seasonal_amplitude_negative_is_clamped_to_zero():
    with reloaded_with_env(SEASONAL_AMPLITUDE=-2.0, SEASONAL_PERIOD_SECONDS=900):
        assert app_module._seasonal_amplitude == pytest.approx(0.0)


@pytest.mark.parametrize("requested", [0, -100])
def test_seasonal_period_non_positive_is_clamped_to_one_second(requested):
    with reloaded_with_env(SEASONAL_AMPLITUDE=0.5, SEASONAL_PERIOD_SECONDS=requested):
        assert app_module._seasonal_period_seconds == pytest.approx(1.0)


def test_index_reports_seasonal_multiplier_matching_the_current_time(client, monkeypatch):
    monkeypatch.setattr(app_module.time, "time", lambda: 225.0)
    response = client.get("/")
    body = response.get_json()
    expected = app_module.seasonal_multiplier(225.0)
    assert body["seasonal_multiplier"] == pytest.approx(expected)


def test_index_traffic_rps_is_unaffected_by_the_seasonal_wave(client, monkeypatch):
    base_rps = app_module._traffic_rps
    for now in (0.0, 225.0, 450.0, 675.0):
        monkeypatch.setattr(app_module.time, "time", lambda now=now: now)
        response = client.get("/")
        body = response.get_json()
        assert body["traffic_rps"] == pytest.approx(base_rps)


def test_traffic_loop_sleep_duration_reflects_the_seasonal_multiplier(monkeypatch):
    monkeypatch.setattr(app_module.time, "time", lambda: 225.0)
    captured = {}

    def fake_sleep(seconds):
        captured["seconds"] = seconds
        raise RuntimeError("stop after one iteration")

    monkeypatch.setattr(app_module.time, "sleep", fake_sleep)
    with pytest.raises(RuntimeError, match="stop after one iteration"):
        app_module._traffic_loop()

    expected_rps = max(
        app_module._traffic_rps * app_module.seasonal_multiplier(225.0), 0.1
    )
    assert captured["seconds"] == pytest.approx(1.0 / expected_rps)


def test_traffic_loop_effective_rps_equals_base_rate_when_wave_disabled(monkeypatch):
    with reloaded_with_env(SEASONAL_AMPLITUDE=0, SEASONAL_PERIOD_SECONDS=900):
        monkeypatch.setattr(app_module.time, "time", lambda: 123.0)
        captured = {}

        def fake_sleep(seconds):
            captured["seconds"] = seconds
            raise RuntimeError("stop after one iteration")

        monkeypatch.setattr(app_module.time, "sleep", fake_sleep)
        with pytest.raises(RuntimeError, match="stop after one iteration"):
            app_module._traffic_loop()

        assert captured["seconds"] == pytest.approx(1.0 / app_module._traffic_rps)


def test_traffic_loop_effective_rps_never_drops_to_zero_even_at_max_amplitude(monkeypatch):
    with reloaded_with_env(SEASONAL_AMPLITUDE=10.0, SEASONAL_PERIOD_SECONDS=900):
        # amplitude clamps to 0.95, so the trough multiplier is 0.05 - at
        # the trough of the wave this is the closest the effective rate
        # gets to zero.
        period = app_module._seasonal_period_seconds
        trough_time = 3 * period / 4
        monkeypatch.setattr(app_module.time, "time", lambda: trough_time)
        captured = {}

        def fake_sleep(seconds):
            captured["seconds"] = seconds
            raise RuntimeError("stop after one iteration")

        monkeypatch.setattr(app_module.time, "sleep", fake_sleep)
        with pytest.raises(RuntimeError, match="stop after one iteration"):
            app_module._traffic_loop()

        multiplier = app_module.seasonal_multiplier(trough_time)
        assert multiplier == pytest.approx(0.05, abs=1e-6)
        expected_rps = max(app_module._traffic_rps * multiplier, 0.1)
        assert captured["seconds"] == pytest.approx(1.0 / expected_rps)
