#!/usr/bin/env bash
# Drives the sample service's POST /error-rate endpoint through a scripted
# incident - ramp up, hold, recover - so each of the 4 burn-rate alert
# tiers in prometheus/alerting_rules.yml can be demonstrated end-to-end
# against a running `make up` stack without manually curling anything.
#
# Usage:
#   scripts/demo-incident.sh [fast|medium-fast|slow|very-slow] [--url URL]
#
# With no tier argument, runs "fast" (the default, and the only tier whose
# `for` duration - 2m - fits in a short demo). The other tiers are included
# for completeness but have long `for` durations (15m/1h/3h): the script
# tells you how long to expect to wait and how to watch along.
set -euo pipefail

SERVICE_URL="http://localhost:8000"
TIER="fast"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --url)
      SERVICE_URL="$2"
      shift 2
      ;;
    fast|medium-fast|slow|very-slow)
      TIER="$1"
      shift
      ;;
    *)
      echo "Usage: $0 [fast|medium-fast|slow|very-slow] [--url URL]" >&2
      exit 1
      ;;
  esac
done

# tier -> (incident error rate, hold duration in seconds, alert `for`, alertname)
case "$TIER" in
  fast)
    INCIDENT_RATE="0.5"
    HOLD_SECONDS=150
    ALERT_FOR="2m"
    ALERT_NAME="SampleServiceErrorBudgetBurnFast"
    ;;
  medium-fast)
    INCIDENT_RATE="0.1"
    HOLD_SECONDS=1080
    ALERT_FOR="15m"
    ALERT_NAME="SampleServiceErrorBudgetBurnMediumFast"
    ;;
  slow)
    INCIDENT_RATE="0.05"
    HOLD_SECONDS=4200
    ALERT_FOR="1h"
    ALERT_NAME="SampleServiceErrorBudgetBurnSlow"
    ;;
  very-slow)
    INCIDENT_RATE="0.02"
    HOLD_SECONDS=12600
    ALERT_FOR="3h"
    ALERT_NAME="SampleServiceErrorBudgetBurnVerySlow"
    ;;
esac

BASELINE_RATE="0.001"

reset_to_baseline() {
  curl -s -X POST "${SERVICE_URL}/error-rate" \
    -H 'Content-Type: application/json' \
    -d "{\"rate\": ${BASELINE_RATE}}" >/dev/null
  echo "-> error rate reset to the healthy baseline (${BASELINE_RATE})"
}
trap reset_to_baseline EXIT

echo "== Demo incident: ${TIER} burn tier (${ALERT_NAME}) =="
echo "   service:   ${SERVICE_URL}"
echo "   error for: ${ALERT_FOR} before it reaches 'firing' (plus the time"
echo "              for the long window's average to catch up)"
echo

echo "[1/3] ramping error rate to ${INCIDENT_RATE} ..."
curl -s -X POST "${SERVICE_URL}/error-rate" \
  -H 'Content-Type: application/json' \
  -d "{\"rate\": ${INCIDENT_RATE}}"
echo
echo "    watch it move from inactive -> pending -> firing at:"
echo "    http://localhost:9090/alerts"
echo

echo "[2/3] holding at ${INCIDENT_RATE} for ${HOLD_SECONDS}s ..."
sleep "${HOLD_SECONDS}"

echo "[3/3] incident window complete."
echo "    check Alertmanager for the routed alert at:"
echo "    http://localhost:9093/#/alerts"
echo
echo "Recovering to baseline now (also runs automatically on exit/Ctrl-C)."
