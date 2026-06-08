# Changelog

## v5.1 — "All Phases, Buildable Depth" (8 jun 2026)

Cada fase del roadmap llevada a su **máxima profundidad construible y verificable**.
Lo que no está es solo aprovisionamiento de infra (arrancar Firecracker, clúster Redis,
k8s), no código. **55 tests en verde** (+16 sobre v5.0).

- **Fase 1** — `DockerBackend.build_args` (puro, testeado): `--cap-drop ALL`, `--network none`,
  `--security-opt no-new-privileges`, `--read-only`, `--user 1000:1000`, `--pids-limit`, `--cpus`.
  `sandbox.preflight()` valida imagen/daemon en el arranque y en `/ready`.
- **Fase 2** — cola de trabajos (`queue.py`): `InProcessQueue` (def., testeada) + `RedisQueue` (Arq);
  worker out-of-process (`worker.py`). `RunManager` ya daba runs durables/reconectables.
- **Fase 3** — tenancy real (`tenancy.py`): usuarios, workspaces, memberships, **cuotas de coste**,
  **audit log** y confinamiento de FS por workspace (`resolve_in_workspace`). Todo testeado.
- **Fase 4** — **retrieval TF-IDF** sin dependencias (`retrieval.py`) inyectado al contexto del coder;
  **gate de revisión con reintento** y helpers de presupuesto en el orquestador.
- **Fase 5** — **checkpoints de todo el workspace** (snapshot/restore, `checkpoints.py` + endpoints),
  **grafo de dependencias** (`depgraph.py`), **agentes en segundo plano** (`background.py`).
- **Fase 6** — **métricas Prometheus** (`metrics.py` + `/metrics`), middleware **request-id**,
  **`/ready`** con preflight de sandbox y backend de persistencia.

### Bugs reales encontrados por los tests nuevos
- **`background.py`**: un método llamado `list` ensombrecía el builtin `list` en las anotaciones de
  tipos posteriores de la clase → `TypeError`. Corregido con `from __future__ import annotations`.
- **`retrieval.tokenize`**: bajaba a minúsculas *antes* de partir camelCase, anulando el split.
  Corregido: el split se hace sobre el token original.

---

## v5.0 — "Platform Foundations" (8 jun 2026)

Cimientos end-to-end de cada fase del `ROADMAP.md`, como **código real que corre
en local hoy** y degrada con elegancia cuando falta la infra pesada (Docker/
Postgres/Redis). **39 tests en verde** (22 de v4.0 + 17 nuevos). No reemplaza el
modo local de un clic: lo amplía.

### Fase Q — quick wins
- **Prompt externalizado y versionado** (`app/prompts/system.md` + loader) — cierra Q3.
- **Telemetría** (`telemetry.py`): tracing OpenTelemetry si está instalado, no-op si no.
- **Arnés de evals** (`app/evals/`): tareas con asserts (file_exists/contains, command_succeeds,
  no_secret_leak), runner pluggable y testeable; `python -m app.evals.harness`.
- **CI** (`.github/workflows/ci.yml`): ruff + pytest + evals + `tsc --noEmit`. `pyproject.toml` con ruff.

### Fase 1 — aislamiento de ejecución
- **Backend de sandbox** (`app/platform/sandbox.py`): `LocalBackend` (actual) + `DockerBackend`
  (contenedor efímero, FS confinado, `--network none`, `--cap-drop ALL`, no-root). Selección por
  `SWARM_SANDBOX=local|docker|auto`; `run_command` lo usa de forma transparente.
- **`Dockerfile.sandbox`** con runtimes de la whitelist y usuario no-root.

### Fase 2 — persistencia + runs durables
- **Persistencia pluggable** (`persistence.py`): SQLite por defecto + **PostgresBackend** (SQLAlchemy,
  `SWARM_DB=postgres`), con degradación a SQLite si falta.
- **Run manager** (`runmanager.py`): los runs corren en segundo plano y **bufferean eventos**, así que
  el cliente puede **desconectarse y reconectar** sin perder el run. Endpoints `POST /run` (ahora durable),
  `GET /api/runs/{id}/stream` (reconexión), `POST /api/runs/{id}/cancel`.

### Fase 3 — auth + RBAC
- **`auth.py`**: tokens HMAC firmados (stdlib, sin deps) con principal user+workspace+rol; RBAC ordenado
  (viewer<editor<owner). Modo local sin secreto = owner implícito (no cambia la experiencia single-user).
  Endpoints `POST /api/auth/token`, `GET /api/auth/me`.

### Fase 4 — enjambre real (paralelo)
- **`orchestrator.py`**: planner → **DAG de subtareas** → **scheduler de batches paralelos** (topo-sort) →
  agentes especializados (architect/coder/reviewer/tester) con `asyncio.gather` → **gate de revisión** +
  blackboard. Endpoint `POST /run/swarm`. Lógica pura (parse_plan, schedule, detección de ciclos) testeada.
- **Frontend**: toggle 🐝 Enjambre / 🜂 Agente único.

### Fase 6 + infra
- `docker-compose.yml` (Postgres + Redis + API), `Dockerfile.api`, `Makefile`, `.env.example`,
  `requirements-platform.txt` (deps opcionales).

### Bug encontrado y corregido durante la verificación
- **Colisión de timestamps de backup**: dos backups en el mismo milisegundo compartían nombre, así que
  un restore hecho en el mismo ms sobrescribía el backup destino y restauraba la versión equivocada.
  `safe_fs.backup_file` ahora garantiza nombres únicos. (Detectado por un test nuevo.)

### Estado honesto
Esto es la **capa de cimientos** de cada fase, no la plataforma terminada. Lo que corre y está testeado:
sandbox local, persistencia SQLite, runs durables in-process, auth/RBAC, scheduling del enjambre, evals.
Lo que queda como camino de producción (documentado, con stubs/IaC listos): Docker/Firecracker en
multi-tenant, workers Redis distribuidos, Postgres en prod, LSP/retrieval por embeddings, k8s.

---

## v4.0 — "Hardened Swarm" (8 jun 2026)

Esta versión resuelve **todos** los hallazgos de `AUDITORIA.md` y eleva el Swarm IDE
de prototipo local a herramienta agéntica robusta: seguridad por capas, estado por
sesión, persistencia, fallback completo y nuevas capacidades de agente. 35 módulos
verificados (compilan) y **22 tests unitarios en verde**.

### 🔐 Seguridad

- **S1 — RCE expuesto a la LAN → cerrado.** El backend ahora enlaza a `127.0.0.1`
  por defecto (`SWARM_HOST`). Exponerlo en la red es un opt-in consciente que
  **exige** `SWARM_AUTH_TOKEN`. Todos los endpoints mutadores/ejecutores y el
  WebSocket de terminal requieren ese token vía `Authorization: Bearer` cuando el
  servidor no es loopback. (`config.py`, `security.py`, `main.py`, `_run_backend.bat`)
- **S2 — Acceso total al disco → acotado.** Los archivos de secretos (`.env*`) están
  vetados para lectura/escritura del agente y de la API, y se ocultan del árbol de
  archivos. (`config.SECRET_FILES`, `tools._is_secret`, `main.py`)
- **S3 — `run_command` endurecido.** Whitelist ampliada y patrones destructivos
  robustos (rm recursivo en cualquier orden, fork-bomb, `dd if=`, `git push --force`,
  format/mkfs/shutdown). (`security.blocked_command`)
- **S4 — SSRF cerrado.** `fetch_url` bloquea IPs privadas, loopback, link-local
  (incl. `169.254.169.254`) y esquemas no http/https; opt-out con
  `SWARM_ALLOW_PRIVATE_FETCH=1`. (`security.validate_outbound_url`)
- **S5 — `.env` ya no es visible ni abrible** desde la UI/editor.
- **S6 — Edición de `.env` sin regex.** El cambio de proyecto reescribe el `.env`
  línea a línea (sin `re.sub`, sin riesgo de backreferences). (`main.switch_project`)
- **S7 — Backups a prueba de traversal.** El bucket de backups se nombra por hash
  SHA-1 de la ruta absoluta en vez de mangling de strings. (`safe_fs._backup_bucket`)

### ⚙️ Concurrencia y estado

- **C1 — Estado global eliminado.** La posición del router, el coste y el detector de
  bucles viven ahora en un `RunContext` por ejecución; las sesiones tienen su propio
  estado en un `SessionManager`. Dos ejecuciones ya no se pisan. (`runtime.py`)
- **C2 — State Guard arreglado.** Se sustituyeron los `contextvars` (que no
  propagaban desde el threadpool de tools) por un registro con lock visible entre
  hilos: la advertencia de “archivos modificados sin actualizar memoria.md” ahora
  sí funciona. (`state_context.py`)
- **C3 — Fallback completo (bug crítico).** El antiguo índice monótono impedía que el
  modo *fast* cayera a los modelos potentes. `RouterState` recorre **todos** los
  modelos disponibles en orden de prioridad, así que el fallback siempre los alcanza.
  Cubierto por test de regresión. (`smart_router.build_order`, `RouterState`)
- **C4 — `PROJECT_ROOT` en runtime.** Se lee vía `config.project_root()` en cada
  llamada (no congelado en import-time); el cambio de proyecto se aplica **en
  caliente** (también actualiza `os.environ`). (`config.py`, `safe_fs.py`, `tools.py`)
- **C5 — Historial por proyecto.** El historial de sesión se guarda bajo el `.swarm`
  del proyecto activo. (`store.py`)
- **C6 — Subagentes async.** `delegate_research`/`delegate_review` y el diff-summary
  corren con `asyncio.to_thread`, sin bloquear el event loop. (`subagents.py`, `tools.py`)

### 🐛 Bugs

- **B1 — Detector de bucles con ventana deslizante** (detecta patrones A,B,A,B y
  ráfagas, ya no se engaña con la sola llamada anterior). (`runtime.LoopDetector`)
- **B2 — Precios alineados con el chain.** Gemini 2.5 (y OpenRouter de pago) ya no se
  facturan a $0. (`cost_tracker._PRICING`)
- **B3 — `sessionCost` real.** El frontend lee el total acumulado del backend
  (`/api/cost`) en vez del `Math.max` de un único run. (`page.tsx`, `api.ts`)
- **B4 — River Cards con resumen real.** Se cableó el camino muerto: al escribir un
  archivo se obtiene su diff (`/api/git/diff`) y se genera el resumen estructurado
  (`/api/diff/summary`). Las tarjetas muestran resumen, +/- líneas y nivel de riesgo.
- **B5 — `is_high_risk_change` ahora se usa** para avisar y sugerir `delegate_review`.
- **B6 — Estado muerto eliminado** (`was_memoria_read` y demás residuos).

### 🧹 Código muerto y duplicado

- **D1** `gitpython` eliminado de `requirements.txt` (nunca se importaba).
- **D2** `get_heavy_model` ahora se usa (fallback de subagentes).
- **D3** `restore_file` como tool del agente eliminado (la restauración va por REST + UI);
  `preview_changes` conservado y documentado en el prompt.
- **D5** Constantes unificadas en `config.py` (`SKIP_DIRS`, `INDEXED_EXTS`); fin de las
  duplicaciones en `tools.py`/`ast_indexer.py` y de los sets de proveedores repetidos.
- **D6** El `diff_out` que se descartaba ya no se propaga inútilmente.

### ✨ Nuevas capacidades agénticas

- **`apply_patch`** — edición multi-archivo/multi-hunk atómica (valida todo antes de
  escribir nada). Ideal para refactors.
- **`update_plan` / `read_plan`** — el agente mantiene una checklist persistente del
  trabajo (estilo IDE agéntico); expuesta en `/api/plan`.
- **`run_tests`** — autodetecta pytest o npm test y los ejecuta; el prompt obliga a
  verificar antes de `git_commit`.
- **Persistencia SQLite** (`store.py`) — runs, eventos y coste sobreviven a reinicios;
  endpoints `/api/runs` y `/api/runs/{id}/events`.
- **Multi-sesión** — `/run` acepta `session_id`; el front genera uno por pestaña.

### 🧪 Calidad

- **Suite de tests** (`backend/tests/`, 22 casos): routing/fallback, precios, guard de
  bucles, auth, SSRF, comandos bloqueados, safe_fs, store, diff stats.
  Ejecuta con `cd backend && python -m pytest`.
- Prompt del sistema reescrito con planificación y verificación obligatorias.

### Nuevas variables de entorno

| Variable | Defecto | Uso |
|----------|---------|-----|
| `SWARM_HOST` | `127.0.0.1` | host de enlace; `0.0.0.0` para LAN (requiere token) |
| `SWARM_PORT` | `8000` | puerto |
| `SWARM_AUTH_TOKEN` | — | secreto compartido; obligatorio si no es loopback |
| `SWARM_CORS_ORIGINS` | `localhost:3000` | orígenes CORS permitidos (coma-separados) |
| `SWARM_ALLOW_PRIVATE_FETCH` | `0` | `1` permite `fetch_url` a IPs privadas |
| `NEXT_PUBLIC_SWARM_TOKEN` | — | token en el frontend (o `localStorage.swarm_token`) |
