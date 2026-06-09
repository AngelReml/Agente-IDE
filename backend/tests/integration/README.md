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
**API encola → worker ejecuta el enjambre → SSE llega desde el bus** (verificado):

```bash
# .env con POSTGRES_PASSWORD, REDIS_PASSWORD, SWARM_AUTH_TOKEN y una clave LLM.
# (La API se expone en 0.0.0.0 → /run exige token; sin SWARM_AUTH_TOKEN da 401.)
docker compose up -d --build --wait
# Sello de seguridad: la API NO tiene Docker; el worker SÍ (vía el proxy).
docker compose exec api    sh -c 'echo "$DOCKER_HOST"'   # vacío
docker compose exec worker sh -c 'echo "$DOCKER_HOST"'   # tcp://docker-proxy:2375
# Lanza un run de CHAT (sin comandos) y observa el SSE: los eventos —incluido el
# stream de tokens— los produce el WORKER y la API solo los retransmite.
curl -N -X POST http://127.0.0.1:8000/run \
  -H 'Content-Type: application/json' -H 'Authorization: Bearer TU_TOKEN' \
  -d '{"task":"Reply in one short sentence: what is Python?","session_id":"smoke"}'
docker compose logs worker | grep run_swarm_job   # → '… status: done'
docker compose down -v
```

> **Caveat de workspace (comandos del agente):** una tarea que ejecute comandos hace
> que el worker lance `docker run -v <cwd>:/workspace swarm-sandbox` contra el daemon
> del host (docker-out-of-docker). El bind-mount lo resuelve el HOST, no el contenedor
> del worker, así que `<cwd>` debe ser una ruta del host compartida (volumen), no una
> ruta interna del worker. Para el smoke de plumbing usa una tarea de chat; para
> ejecución real de comandos en plataforma falta cablear ese volumen de workspace
> (PROJECT_ROOT/workspace compartido worker↔sandbox). Construye antes la imagen del
> sandbox: `docker build -f backend/Dockerfile.sandbox -t swarm-sandbox:latest backend`.
