.PHONY: help install test lint eval run sandbox-image up down integration

REDIS_PASSWORD ?= devredis

help:
	@echo "Swarm IDE — comandos de desarrollo"
	@echo "  make install        Instala deps del backend"
	@echo "  make test           Ejecuta la suite pytest"
	@echo "  make lint           ruff check"
	@echo "  make eval           Ejecuta el arnés de evals (omite sin claves)"
	@echo "  make run            Backend en local (loopback)"
	@echo "  make sandbox-image  Construye la imagen del sandbox (Fase 1)"
	@echo "  make up / make down Levanta/baja el stack de plataforma (Postgres+Redis+API)"
	@echo "  make integration    Smoke de integración (Fase 6): Redis real + RedisBus/worker/arq"

install:
	cd backend && pip install -r requirements.txt

test:
	cd backend && python -m pytest -q

lint:
	cd backend && ruff check app || true

eval:
	cd backend && python -m app.evals.harness

run:
	cd backend && SWARM_HOST=127.0.0.1 uvicorn app.main:app --reload --port 8000

sandbox-image:
	cd backend && docker build -f Dockerfile.sandbox -t swarm-sandbox:latest .

up:
	docker compose up -d --build

down:
	docker compose down

# Smoke de integración del path out-of-process (Fase 6, paso 4): levanta SOLO Redis
# real, instala las deps de plataforma y corre los tests que ejercitan RedisBus,
# worker.run_swarm_job sobre el bus, y el round-trip de la cola arq. No necesita
# claves LLM ni Docker-in-Docker. POSTGRES_PASSWORD es un dummy (no se arranca PG).
integration:
	POSTGRES_PASSWORD=ci-dummy REDIS_PASSWORD=$(REDIS_PASSWORD) docker compose up -d --wait redis
	cd backend && python -m pip install -q redis arq
	cd backend && SWARM_TEST_REDIS_URL=redis://:$(REDIS_PASSWORD)@127.0.0.1:6379/0 \
		python -m pytest tests/integration -v ; status=$$? ; \
		cd .. && POSTGRES_PASSWORD=ci-dummy REDIS_PASSWORD=$(REDIS_PASSWORD) docker compose down ; \
		exit $$status
