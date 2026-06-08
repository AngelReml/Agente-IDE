.PHONY: help install test lint eval run sandbox-image up down

help:
	@echo "Swarm IDE — comandos de desarrollo"
	@echo "  make install        Instala deps del backend"
	@echo "  make test           Ejecuta la suite pytest"
	@echo "  make lint           ruff check"
	@echo "  make eval           Ejecuta el arnés de evals (omite sin claves)"
	@echo "  make run            Backend en local (loopback)"
	@echo "  make sandbox-image  Construye la imagen del sandbox (Fase 1)"
	@echo "  make up / make down Levanta/baja el stack de plataforma (Postgres+Redis+API)"

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
