# ss-sens developer entrypoints.
SHELL := /bin/bash
PROJECT_ROOT := $(patsubst %/,%,$(dir $(abspath $(lastword $(MAKEFILE_LIST)))))
VENV := $(PROJECT_ROOT)/.venv
PY := $(VENV)/bin/python
PYTHON_VERSION ?= 3.11
DATA_DIR ?= .data
DATA_ROOT := $(if $(filter /%,$(DATA_DIR)),$(DATA_DIR),$(PROJECT_ROOT)/$(DATA_DIR))
PYTEST_CACHE := -o cache_dir=$(DATA_ROOT)/cache/pytest
ENV := source "$(PROJECT_ROOT)/scripts/shared/common.sh"; ssc_load_env;

unexport VIRTUAL_ENV

export RUFF_CACHE_DIR := $(DATA_ROOT)/cache/ruff
export UV_CACHE_DIR ?= $(DATA_ROOT)/uv-cache

.DEFAULT_GOAL := help

.PHONY: help bootstrap venv lock format format-check lint test test-stack \
 docker-check ss-sens-up ss-sens-up-min ss-sens-up-video ss-sens-down \
 ss-sens-logs ss-sens-status ss-sens-metrics-up ss-sens-release \
 ss-sens-release-min ss-sens-release-video ss-sens-release-metrics \
 lint-doc-links lint-spec-plan plan-status ci ci-github

help: ## List available targets
	@awk 'BEGIN {FS = ":.*## "; print "Usage: make \n"} /^[a-zA-Z0-9_.-]+:.*## / {printf "  %-24s %s\n", $$1, $$2}' $(MAKEFILE_LIST)

bootstrap: ## Create/update .venv from uv.lock with every extra
	@command -v uv >/dev/null 2>&1 || { echo "ERROR: uv is required"; exit 1; }
	@$(ENV) uv sync --locked --all-extras --python "$(PYTHON_VERSION)"

venv: bootstrap ## Alias for bootstrap

lock: ## Refresh uv.lock after dependency changes
	@$(ENV) uv lock

format: ## Format production code and tests with Ruff
	@"$(VENV)/bin/ruff" format src tests
	@"$(VENV)/bin/ruff" check --fix src tests

format-check: ## Check Python formatting without changing files
	@"$(VENV)/bin/ruff" format --check src tests

lint: format-check ## Run Ruff lint checks
	@"$(VENV)/bin/ruff" check src tests

test: ## Run unit tests
	@$(ENV) "$(PY)" -m pytest tests/unit $(PYTEST_CACHE)

test-stack: docker-check ## Stack health tests (needs make ss-sens-up-min)
	@$(ENV) "$(PY)" -m pytest tests/ss_sens $(PYTEST_CACHE)

docker-check: ## Fail if the Docker daemon is not reachable
	@if ! docker info >/dev/null 2>&1; then \
		echo ""; \
		echo "Docker is not accessible (permission denied or daemon not running)."; \
		echo ""; \
		echo "Safe fix: add your user to the docker group:"; \
		echo "  sudo usermod -aG docker $$USER"; \
		echo "Then log out and back in, or in this terminal run: newgrp docker"; \
		echo ""; \
		exit 1; \
	fi

ss-sens-up: docker-check ## Bootstrap + start LoRaWAN + MQTT + ss-sens serve
	COMPOSE_PROFILES=lorawan "$(PROJECT_ROOT)/scripts/ss-sens/ss-sens-bootstrap.sh" up -d

ss-sens-up-min: docker-check ## Start min bundle (LoRaWAN + MQTT + ss-sens serve)
	COMPOSE_PROFILES=lorawan "$(PROJECT_ROOT)/scripts/ss-sens/ss-sens-bootstrap.sh" up -d

ss-sens-up-video: docker-check ## Start MQTT + ss-sens serve (Frigate stays in ss-video)
	COMPOSE_PROFILES= "$(PROJECT_ROOT)/scripts/ss-sens/ss-sens-bootstrap.sh" up -d

ss-sens-down: docker-check ## Stop the ss-sens stack
	COMPOSE_PROFILES=lorawan,metrics "$(PROJECT_ROOT)/scripts/ss-sens/ss-sens-compose.sh" down

ss-sens-logs: docker-check ## Stream ss-sens stack logs
	"$(PROJECT_ROOT)/scripts/ss-sens/ss-sens-compose.sh" logs -f --tail=100

ss-sens-status: docker-check ## Show container status and resource usage
	"$(PROJECT_ROOT)/scripts/ss-sens/ss-sens-compose.sh" ps
	@echo ""
	@docker stats --no-stream --format "table {{.Name}}\t{{.CPUPerc}}\t{{.MemUsage}}\t{{.NetIO}}" \
	  $$("$(PROJECT_ROOT)/scripts/ss-sens/ss-sens-compose.sh" ps -q 2>/dev/null) 2>/dev/null || true

ss-sens-metrics-up: docker-check ## Start LoRaWAN stack plus Prometheus / Grafana / cAdvisor
	COMPOSE_PROFILES=lorawan,metrics "$(PROJECT_ROOT)/scripts/ss-sens/ss-sens-bootstrap.sh" up -d

ss-sens-release: ## Build standard offline bundle (amd64); set VERSION= to tag
	"$(PROJECT_ROOT)/scripts/ss-sens/ss-sens-release.sh" --arch amd64 --bundle standard $(if $(VERSION),--version $(VERSION),) --yes

ss-sens-release-min: ## Build min bundle (LoRaWAN + MQTT)
	"$(PROJECT_ROOT)/scripts/ss-sens/ss-sens-release.sh" --arch amd64 --bundle min $(if $(VERSION),--version $(VERSION),) --yes

ss-sens-release-video: ## Build MQTT-only bundle (no LoRaWAN; Frigate stays in ss-video)
	"$(PROJECT_ROOT)/scripts/ss-sens/ss-sens-release.sh" --arch amd64 --bundle video $(if $(VERSION),--version $(VERSION),) --yes

ss-sens-release-metrics: ## Build standard bundle plus Prometheus/Grafana images
	"$(PROJECT_ROOT)/scripts/ss-sens/ss-sens-release.sh" --arch amd64 --bundle standard --with-metrics $(if $(VERSION),--version $(VERSION),) --yes

lint-doc-links: ## Check that relative Markdown links and anchors resolve
	@"$(PY)" -m ss_kit.quality.doc_links --root "$(PROJECT_ROOT)"

lint-spec-plan: ## Check capability registry, task structure, status, and ordering
	@"$(PY)" -m ss_kit.quality.plan_integrity --root "$(PROJECT_ROOT)"

plan-status: ## Count tasks by lane/status and show the next eligible work
	@"$(PY)" -m ss_kit.quality.plan_summary --root "$(PROJECT_ROOT)"

ci: bootstrap lint lint-doc-links lint-spec-plan test ## Required local and GitHub CI gate

ci-github: ci ## Explicit GitHub Actions entrypoint
