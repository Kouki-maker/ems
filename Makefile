.PHONY: help install run test clean docker-up docker-down docker-logs

DOCKER_COMPOSE := docker-compose
DOCKER_COMPOSE_DEV := docker-compose --profile dev
DOCKER_COMPOSE_SIM := docker-compose --profile simulators

help:
	@echo "Electra EMS - Available Commands"
	@echo "=================================="
	@echo ""
	@echo "🚀 Quick Start:"
	@echo "  make dev-setup          - Complete dev environment setup"
	@echo "  make demo               - Start API + simulators"
	@echo ""
	@echo "🐳 Docker Commands:"
	@echo "  make docker-up          - Start API only"
	@echo "  make docker-dev         - Start with PgAdmin & MQTT Explorer"
	@echo "  make docker-sim         - Start API + simulators"
	@echo "  make docker-down        - Stop all services"
	@echo "  make docker-logs        - View API logs"
	@echo "  make docker-clean       - Stop and remove volumes"
	@echo ""
	@echo "🔌 Simulators:"
	@echo "  make sim-charger [ID]   - Start charger simulator"
	@echo "  make sim-bess           - Start BESS simulator"
	@echo "  make sim-all            - Start all simulators"
	@echo "  make sim-scenario [N]   - Run scenario 1, 2, or 3"
	@echo ""
	@echo "🗄️  Database:"
	@echo "  make migrate            - Run migrations"
	@echo "  make create-migration   - Create new migration"
	@echo "  make db-shell           - Connect to PostgreSQL"
	@echo "  make db-reset           - Reset database"
	@echo ""
	@echo "🧪 Testing:"
	@echo "  make test               - Run tests"
	@echo "  make test-mqtt          - Test MQTT connectivity"
	@echo ""
	@echo "🛠️  Utilities:"
	@echo "  make clean              - Clean temp files"
	@echo "  make fix-permissions    - Fix script permissions"

# Quick start
dev-setup: fix-permissions docker-up migrate
	@echo ""
	@echo "✓ Development environment ready!"
	@echo "  API: http://localhost:8000/docs"
	@echo "  DB: localhost:5432 (electra/electra_password)"
	@echo "  MQTT: localhost:1883"

demo: docker-sim
	@echo ""
	@echo "✓ Demo started with simulators!"
	@echo "  API: http://localhost:8000/docs"
	@echo "  Watch: make docker-logs"

# Docker commands
docker-up:
	@echo "Starting Electra EMS..."
	$(DOCKER_COMPOSE) up -d postgres mosquitto
	@sleep 5
	$(DOCKER_COMPOSE) up -d ems-api
	@echo "✓ Services started"
	@echo "  API: http://localhost:8000"
	@echo "  Docs: http://localhost:8000/docs"

docker-dev:
	@echo "Starting development environment..."
	$(DOCKER_COMPOSE_DEV) up -d
	@echo "✓ Services started"
	@echo "  API: http://localhost:8000"
	@echo "  PgAdmin: http://localhost:5050"
	@echo "  MQTT Explorer: http://localhost:4000"

docker-sim:
	@echo "Starting with simulators..."
	$(DOCKER_COMPOSE_SIM) up -d
	@sleep 10
	@echo "✓ All services and simulators started"
	@echo "  Monitor with: make docker-logs"

docker-down:
	$(DOCKER_COMPOSE) down

docker-restart: docker-down docker-up

docker-clean:
	$(DOCKER_COMPOSE) down -v

docker-logs:
	$(DOCKER_COMPOSE) logs -f ems-api

docker-logs-all:
	$(DOCKER_COMPOSE) logs -f

docker-logs-mqtt:
	$(DOCKER_COMPOSE) logs -f mosquitto

docker-logs-sim:
	$(DOCKER_COMPOSE) logs -f charger-sim-1 charger-sim-2 bess-sim

# Simulators (local)
sim-charger:
	@chmod +x scripts/run_simulator.sh
	./scripts/run_simulator.sh charger ${ID} interactive

sim-charger-auto:
	python simulators/charger_simulator.py \
		--station-id ELECTRA_PARIS_15 \
		--charger-id ${ID} \
		--mode auto \
		--duration 300

sim-bess:
	@chmod +x scripts/run_simulator.sh
	./scripts/run_simulator.sh bess interactive

sim-bess-auto:
	python simulators/bess_simulator.py \
		--station-id ELECTRA_PARIS_15 \
		--mode auto \
		--duration 300

sim-all:
	@chmod +x scripts/run_simulator.sh
	./scripts/run_simulator.sh all

sim-scenario:
	@chmod +x scripts/run_scenario_mqtt.py
	python scripts/run_scenario_mqtt.py ${N}

# Database
migrate:
	$(DOCKER_COMPOSE) exec ems-api alembic upgrade head
	@echo "✓ Migrations applied"

create-migration:
	@read -p "Migration message: " msg; \
	$(DOCKER_COMPOSE) exec ems-api alembic revision --autogenerate -m "$$msg"

db-shell:
	$(DOCKER_COMPOSE) exec postgres psql -U electra -d electra_ems

db-reset:
	@echo "⚠️  This will delete ALL data!"
	@read -p "Type 'yes' to confirm: " confirm; \
	if [ "$$confirm" = "yes" ]; then \
		$(DOCKER_COMPOSE) down -v; \
		$(DOCKER_COMPOSE) up -d postgres mosquitto; \
		sleep 10; \
		$(DOCKER_COMPOSE) up -d ems-api; \
		sleep 10; \
		make migrate; \
	fi

# Testing
test:
	python -m pytest app/tests/test_scenarios.py -v -s

test-mqtt:
	@echo "Testing MQTT connectivity..."
	@python -c "import paho.mqtt.client as mqtt; \
		c = mqtt.Client(); \
		c.connect('localhost', 1883); \
		print('✓ MQTT connection successful')"

# Utilities
clean:
	@find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	@find . -type f -name "*.pyc" -delete
	@rm -rf test_results/
	@echo "✓ Cleanup completed"

fix-permissions:
	@chmod +x scripts/*.sh 2>/dev/null || true
	@chmod +x scripts/*.py 2>/dev/null || true
	@chmod +x simulators/*.py 2>/dev/null || true
	@echo "✓ Permissions fixed"

install:
	pip install -r requirements.txt

# Monitoring
monitor-mqtt:
	@echo "Monitoring MQTT messages (Ctrl+C to stop)..."
	@mosquitto_sub -h localhost -t 'electra/#' -v

status:
	@echo "Services Status:"
	@$(DOCKER_COMPOSE) ps
	@echo ""
	@echo "API Health:"
	@curl -s http://localhost:8000/health | python -m json.tool || echo "API not responding"
