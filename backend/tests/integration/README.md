# Pruebas de integración (Fase 6, paso 4 — ejecución out-of-process)

Estos tests validan los *seams* que la suite normal solo puede falsear: el bus de
eventos sobre **Redis real** (`RedisBus`, Redis Streams), el job del worker
publicando al bus de extremo a extremo, y el round-trip de la cola **arq**
(encolar → worker burst → ejecutado). No necesitan claves LLM ni Docker-in-Docker.

## Cómo correrlas

La forma fácil (levanta Redis con docker-compose, corre y baja):

```bash
make integration
# o con tu propia contraseña:
make integration REDIS_PASSWORD=miclave
```

Manualmente contra cualquier Redis:

```bash
# 1) deps de plataforma en tu entorno de test
pip install -r backend/requirements-platform.txt
# 2) apunta a un Redis accesible y corre
SWARM_TEST_REDIS_URL=redis://:pass@127.0.0.1:6379/0 \
  python -m pytest backend/tests/integration -v
```

Si `SWARM_TEST_REDIS_URL` no está definido o el Redis no responde, **todo el
módulo se omite** (skip), por eso no afecta a `make test` ni a CI.

## Smoke del stack completo (manual, requiere claves LLM)

Lo anterior cubre el transporte sin LLM. Para ver el flujo real
**API encola → worker ejecuta el enjambre en contenedor → SSE llega desde el bus**:

```bash
# .env con POSTGRES_PASSWORD, REDIS_PASSWORD y una clave (OPENAI/ANTHROPIC/…)
make sandbox-image          # imagen del sandbox que usa el worker
docker compose up -d --build --wait
# lanza un run y observa el SSE (los eventos los produce el WORKER, no la API):
curl -N -X POST http://127.0.0.1:8000/run \
  -H 'Content-Type: application/json' \
  -d '{"task":"crea hola.py que imprima hola","session_id":"smoke"}'
# comprueba que la API NO tiene acceso a Docker (debe fallar): la API ya no monta
# el socket ni define DOCKER_HOST; solo el servicio `worker` habla con el proxy.
docker compose exec api sh -c 'echo $DOCKER_HOST'   # vacío
docker compose logs worker | tail
docker compose down
```
