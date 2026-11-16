.PHONY: up down logs check check-prometheus check-alertmanager lint burn reset demo

# Bring up the demo stack (sample-service + Prometheus + Alertmanager + Grafana).
up:
	docker compose up -d --build

down:
	docker compose down

logs:
	docker compose logs -f

# Validate the Prometheus rule files and config without needing promtool
# installed locally - runs it inside the official Prometheus image.
check: check-prometheus check-alertmanager

check-prometheus:
	docker run --rm -v "$$PWD/prometheus:/etc/prometheus:ro" \
		--entrypoint promtool prom/prometheus:latest \
		check config /etc/prometheus/prometheus.yml
	docker run --rm -v "$$PWD/prometheus:/etc/prometheus:ro" \
		--entrypoint promtool prom/prometheus:latest \
		check rules /etc/prometheus/recording_rules.yml /etc/prometheus/alerting_rules.yml \
		/etc/prometheus/latency_recording_rules.yml /etc/prometheus/latency_alerting_rules.yml \
		/etc/prometheus/saturation_recording_rules.yml /etc/prometheus/saturation_alerting_rules.yml

check-alertmanager:
	docker run --rm -v "$$PWD/alertmanager:/etc/alertmanager:ro" \
		--entrypoint amtool prom/alertmanager:latest \
		check-config /etc/alertmanager/alertmanager.yml

# Lint the sample service with ruff (pip install -r sample-service/requirements-dev.txt).
lint:
	ruff check sample-service/

# Push the sample service's synthetic error rate up to simulate an incident.
# Usage: make burn RATE=0.5
burn:
	curl -s -X POST localhost:8000/error-rate -H 'Content-Type: application/json' \
		-d '{"rate": $(or $(RATE),0.5)}'

# Put the sample service back to its healthy baseline error rate.
reset:
	curl -s -X POST localhost:8000/error-rate -H 'Content-Type: application/json' \
		-d '{"rate": 0.001}'

# Run the scripted incident demo (ramp up, hold, recover) against a running
# stack. Usage: make demo TIER=fast (default: fast; also medium-fast, slow,
# very-slow - see scripts/demo-incident.sh for their much longer hold times).
demo:
	scripts/demo-incident.sh $(or $(TIER),fast)
