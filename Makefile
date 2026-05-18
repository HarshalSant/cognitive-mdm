.PHONY: help dev-up dev-down seed test lint proto build clean run-service

SHELL := /bin/bash
SERVICES := api-gateway ingestion-service entity-resolution semantic-engine graph-service governance-service agent-service copilot-service

help: ## Show this help
	@awk 'BEGIN {FS = ":.*##"; printf "\nUsage:\n  make \033[36m<target>\033[0m\n\nTargets:\n"} /^[a-zA-Z_-]+:.*?##/ { printf "  \033[36m%-20s\033[0m %s\n", $$1, $$2 }' $(MAKEFILE_LIST)

install: ## Install root dev tools
	pip install pre-commit
	pre-commit install
	npm install --prefix frontend

dev-up: ## Start all services with Docker Compose
	cp -n .env.example .env || true
	docker compose up -d --build
	@echo "Waiting for services to be healthy..."
	@sleep 10
	@echo "Dashboard: http://localhost:3000"
	@echo "API Docs:  http://localhost:8000/docs"
	@echo "Neo4j:     http://localhost:7474"
	@echo "Kafka UI:  http://localhost:8080"
	@echo "Grafana:   http://localhost:3001"

dev-down: ## Stop all services
	docker compose down

dev-clean: ## Stop and remove all volumes
	docker compose down -v --remove-orphans

seed: ## Seed sample data into all stores
	docker compose exec ingestion-service python -m src.seed

test: ## Run all service tests
	@for svc in $(SERVICES); do \
		echo "Testing $$svc..."; \
		docker compose exec $$svc pytest tests/ -v --tb=short || exit 1; \
	done

test-service: ## Run tests for a single service: make test-service SERVICE=entity-resolution
	docker compose exec $(SERVICE) pytest tests/ -v

lint: ## Lint all Python services
	@for svc in $(SERVICES); do \
		echo "Linting $$svc..."; \
		cd services/$$svc && ruff check src/ && cd ../..; \
	done

format: ## Format all Python services
	@for svc in $(SERVICES); do \
		cd services/$$svc && ruff format src/ && cd ../..; \
	done

proto: ## Compile gRPC proto files
	@for proto in shared/proto/*.proto; do \
		python -m grpc_tools.protoc \
			-I shared/proto \
			--python_out=shared/generated \
			--grpc_python_out=shared/generated \
			$$proto; \
	done
	@echo "Proto files compiled."

build: ## Build all Docker images
	docker compose build

logs: ## Tail logs for a service: make logs SERVICE=entity-resolution
	docker compose logs -f $(SERVICE)

logs-all: ## Tail all service logs
	docker compose logs -f

run-service: ## Run a service locally (no Docker): make run-service SERVICE=entity-resolution
	cd services/$(SERVICE) && uvicorn src.main:app --reload --port $$(grep -E "^PORT" .env | cut -d= -f2)

ps: ## Show running containers and health
	docker compose ps

neo4j-console: ## Open Neo4j browser
	open http://localhost:7474

api-docs: ## Open API documentation
	open http://localhost:8000/docs

dashboard: ## Open frontend dashboard
	open http://localhost:3000

migrate: ## Run database migrations
	docker compose exec api-gateway alembic upgrade head

clean: ## Remove all build artifacts
	find . -type d -name __pycache__ -exec rm -rf {} +
	find . -type f -name "*.pyc" -delete
	find . -type d -name .pytest_cache -exec rm -rf {} +
	find . -type d -name .ruff_cache -exec rm -rf {} +
