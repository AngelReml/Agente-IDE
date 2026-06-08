# Dossier Técnico — Crystal Swarm IDE (Swarm IDE v5.1)

> Documento de especificaciones técnicas del proyecto **swarm-ide**, generado el **8 de junio de 2026**.
> Refleja el estado real del código y del entorno verificado en la puesta en marcha sobre Windows.

---

## 1. Resumen ejecutivo

**Swarm IDE** es un entorno de desarrollo (IDE) multi-agente que ejecuta tareas de programación a partir de instrucciones en lenguaje natural. Un agente de IA —individual o en **enjambre paralelo**— planifica, lee el proyecto, crea/edita archivos, ejecuta tests, hace commits y reporta cada paso en tiempo real.

- **Filosofía:** *local-first* (arranque de un clic en Windows, sin Docker) que escala a **plataforma multi-tenant** sobre la misma base de código.
- **Versión actual:** v5.1 — "All Phases, Buildable Depth" (8 jun 2026).
- **Nombre de producto (UI):** *Crystal Swarm IDE — Final Chronicles* (estética Final Fantasy IX).
- **Licencia:** MIT.

| Métrica | Valor |
|---|---|
| Módulos Python (backend `app/`) | 29 |
| Líneas de código backend (Python) | ~4.027 |
| Líneas de código frontend (TS/TSX) | ~2.940 |
| Endpoints REST | 38 + 1 WebSocket |
| Modelos LLM soportados | 24 (en 8 proveedores) |
| Suite de tests | 55 tests en 5 archivos |

---

## 2. Arquitectura general

Dos modos de despliegue sobre el mismo código; cada pieza **degrada con elegancia** si falta la infraestructura pesada (Docker/Postgres/Redis), cayendo al equivalente local.

```
┌──────────────────────────┐         ┌──────────────────────────────────┐
│  FRONTEND (Next.js)      │  REST   │  BACKEND (FastAPI)               │
│  http://localhost:3000   │ ◄─────► │  http://127.0.0.1:8000           │
│  - Editor Monaco         │  SSE    │  - Agente ReAct (LangGraph)      │
│  - Terminal (WebSocket)  │ ◄─────► │  - Orquestador de enjambre       │
│  - File Explorer / River │  WS     │  - Router de 24 modelos          │
└──────────────────────────┘         │  - SQLite (runs/eventos/coste)   │
                                      └──────────────────────────────────┘
```

| | Local-first | Plataforma |
|---|---|---|
| Arranque | `INICIAR.bat` | `docker compose up` |
| Host | `127.0.0.1` (loopback) | `0.0.0.0` + token |
| Sandbox de ejecución | local (subprocess) | Docker (contenedor efímero) |
| Persistencia | SQLite | PostgreSQL |
| Autenticación | owner implícito | tokens HMAC + RBAC |
| Cola de trabajos | in-process | Redis + workers (Arq) |

---

## 3. Stack tecnológico

### 3.1 Backend (Python)

- **Runtime verificado:** Python **3.10.11** (entorno virtual `backend/venv`).
- **Framework web:** FastAPI `0.115.0` sobre Uvicorn `0.30.6` (`[standard]`).
- **Motor de agentes:** LangGraph `≥0.2.0` + LangChain Core `≥0.3.0`.
- **Conectores LLM:** `langchain-openai`, `langchain-anthropic`, `langchain-groq`, SDK `openai ≥1.50`, SDK `anthropic ≥0.40`.
- **Streaming:** `sse-starlette 2.1.3` (Server-Sent Events).
- **Validación/datos:** Pydantic `≥2.0`.
- **Configuración:** `python-dotenv 1.0.1`.
- **Tests:** Pytest `≥8.0`.

**Dependencias opcionales de plataforma** (`requirements-platform.txt`, el núcleo funciona sin ellas):
- Persistencia Postgres: `sqlalchemy ≥2.0`, `psycopg[binary] ≥3.1`.
- Cola/pub-sub: `arq ≥0.25`, `redis ≥5.0`.
- Observabilidad: `opentelemetry-api/sdk/exporter-otlp ≥1.25`.

### 3.2 Frontend (Node.js)

- **Runtime verificado:** Node.js **24.12.0**, npm **11.6.2**.
- **Framework:** Next.js `15.3.2` (React `19`, React-DOM `19`).
- **Editor de código:** Monaco (`@monaco-editor/react 4.6`, `monaco-editor 0.52`) — el mismo motor que VS Code.
- **Iconos:** `lucide-react 0.441`.
- **Estilos:** Tailwind CSS `3.4` + PostCSS + Autoprefixer.
- **Lenguaje:** TypeScript `5`.

### 3.3 Herramientas de sistema

- Git **2.52.0** (control de versiones; el agente expone comandos `git_*`).

---

## 4. Estructura de módulos del backend (`backend/app/`)

| Módulo | Responsabilidad |
|---|---|
| `main.py` | FastAPI: endpoints REST + SSE + WebSocket de terminal |
| `config.py` | Configuración central (host, token, sandbox, db, límites, constantes) |
| `security.py` | Auth de request, guard SSRF, bloqueo de comandos destructivos |
| `auth.py` | Tokens HMAC firmados, principal user+workspace+rol, RBAC (viewer<editor<owner) |
| `graph.py` | Agente único ReAct + streaming SSE (prompt externalizado) |
| `orchestrator.py` | Enjambre: planner → DAG → batches paralelos → review gate |
| `runmanager.py` | Runs durables/reconectables (buffer de eventos in-process) |
| `runtime.py` | Estado por run/sesión: `RouterState`, `RunContext`, `LoopDetector` |
| `smart_router.py` | Chain de 24 modelos, routing y fallback completo |
| `cost_tracker.py` | Precios y coste en USD; base de presupuestos |
| `tools.py` | Herramientas del agente (fs, git, cmd, http, plan, tests, apply_patch) |
| `safe_fs.py` | Filesystem seguro + backups por hash (base de checkpoints) |
| `ast_indexer.py` | Índice semántico del proyecto (base de retrieval) |
| `state_context.py` | Tracking de mutaciones (State Guard, con lock entre hilos) |
| `diff_parser.py` | Resumen de diffs con IA |
| `store.py` | Persistencia SQLite (runs, eventos, coste, historial) |
| `persistence.py` | Selector de backend de persistencia: SQLite \| Postgres |
| `queue.py` | Cola de trabajos: `InProcessQueue` \| `RedisQueue` (Arq) |
| `worker.py` | Entrypoint del worker Arq (escala out-of-process) |
| `tenancy.py` | Usuarios/workspaces/roles/cuotas/audit + confinamiento de FS |
| `retrieval.py` | Retrieval TF-IDF del repo (contexto del enjambre) |
| `checkpoints.py` | Snapshot/restore de todo el workspace (time-travel) |
| `depgraph.py` | Grafo de imports/dependencias |
| `background.py` | Registro de agentes en segundo plano/programados |
| `metrics.py` | Métricas Prometheus + middleware request-id |
| `telemetry.py` | Tracing OpenTelemetry con fallback no-op |
| `platform/sandbox.py` | Ejecución: `LocalBackend` \| `DockerBackend` (endurecido) |
| `prompts/system.md` | Prompt del sistema versionado |
| `evals/harness.py` | Arnés de evals con asserts |

---

## 5. API REST + tiempo real

Base: `http://127.0.0.1:8000`. Los endpoints marcados con 🔒 requieren autenticación (`Depends(require_auth)`); obligatoria cuando el servidor no enlaza a loopback.

### Salud y observabilidad
- `GET /health` — liveness.
- `GET /ready` — readiness con preflight de sandbox y backend de persistencia.
- `GET /metrics` — métricas en formato Prometheus (texto plano).

### Ejecución de agentes
- 🔒 `POST /run` — run durable de agente único (acepta `session_id`).
- 🔒 `POST /run/swarm` — run de enjambre paralelo.
- 🔒 `GET /api/runs/{run_id}/stream` — reconexión SSE a un run en curso (replay + tail).
- 🔒 `POST /api/runs/{run_id}/cancel` — cancelación de run.
- `GET /api/runs` — listado de runs persistidos.
- `GET /api/runs/{run_id}/events` — eventos de un run.
- `GET /api/plan` — checklist persistente de la tarea.

### Archivos y Git
- `GET /api/files` — árbol de archivos (oculta secretos `.env*`).
- `GET /api/file` — lee un archivo · 🔒 `POST /api/file` — escribe · 🔒 `DELETE /api/file` — borra.
- `GET /api/git/status` · `GET /api/git/diff` · `GET /api/git/log`.

### Modelos y routing
- `GET /api/models` · 🔒 `POST /api/models/reset` · 🔒 `POST /api/models/select`.
- `GET /api/routing/mode` · 🔒 `POST /api/routing/mode` (⚡ Fast / 🔥 Power).

### Contexto, coste y backups
- `GET /api/chat/context` · 🔒 `POST /api/chat/clear`.
- `GET /api/cost` — coste acumulado de sesión (tokens + USD).
- `GET /api/backups` · 🔒 `POST /api/restore`.
- `GET /api/checkpoints` · 🔒 `POST /api/checkpoints` · 🔒 `POST /api/checkpoints/{id}/restore`.
- 🔒 `POST /api/diff/summary` · 🔒 `POST /api/index/rebuild`.

### Auth y proyecto
- `POST /api/auth/token` · `GET /api/auth/me`.
- `GET /api/project` · 🔒 `POST /api/project/switch` · `GET /api/project/recents`.

### Tiempo real
- `WS /ws/terminal` — terminal PTY nativa por WebSocket (PowerShell en Windows), con guard de comandos.

---

## 6. Modelos de IA y routing

Chain de **24 modelos en 8 proveedores** con **fallback automático**: el agente empieza en el modelo apropiado según el modo y avanza si hay error de cuota, rate-limit o saldo insuficiente.

| Modo | Inicio del chain | Ideal para |
|---|---|---|
| ⚡ **Fast** | Groq → GLM → DeepSeek → HuggingFace | tareas simples, bajo coste |
| 🔥 **Power** | Anthropic → OpenAI → Gemini | tareas complejas, máxima calidad |

**Proveedores:** Anthropic (Claude Opus/Sonnet/Haiku 4.5), OpenAI (GPT-4o / 4o Mini), Groq (Llama 3.3 70B / 3.1 8B), GLM/ZhipuAI (GLM-4 Plus/Air/Flash), Google Gemini (2.5 Flash/Pro, 2.0 Flash), DeepSeek (V3/R1), HuggingFace (Qwen2.5 Coder 32B/72B, Llama 3.3 70B) y OpenRouter (Claude/Gemini/Qwen3/Llama/Gemma como pasarela).

> **Estado verificado en este equipo:** las 8 claves API están configuradas en `.env` (Anthropic, OpenAI, Groq, GLM, Gemini, DeepSeek, HuggingFace, OpenRouter), por lo que el chain de fallback completo está disponible.

---

## 7. Herramientas del agente

| Herramienta | Descripción |
|---|---|
| `read_file` | Lee archivos del proyecto (secretos protegidos) |
| `write_file` / `edit_file` | Crea/sobreescribe · edición quirúrgica de fragmento exacto |
| `apply_patch` | Edición multi-archivo/multi-hunk **atómica** (valida antes de escribir) |
| `update_plan` / `read_plan` | Checklist persistente de la tarea |
| `run_tests` | Autodetecta y ejecuta pytest o `npm test` antes de cada commit |
| `list_files` / `grep_search` / `get_semantic_map` | Listado, búsqueda de texto y mapa AST |
| `run_command` | Ejecuta comandos (pip, npm, pytest, ruff…) con whitelist + guard |
| `fetch_url` | GET HTTP con protección SSRF |
| `delegate_research` / `delegate_review` | Subagentes asíncronos (investigación / code review) |
| `git_*` | status, diff, commit, log, branch, push |

---

## 8. Seguridad (modelo por capas)

- **Enlace a loopback por defecto** (`SWARM_HOST=127.0.0.1`). Exponer en LAN (`0.0.0.0`) es opt-in consciente que **exige** `SWARM_AUTH_TOKEN`; todos los endpoints mutadores/ejecutores y el WebSocket lo requieren vía `Authorization: Bearer`.
- **Secretos vetados:** los archivos `.env*` no son legibles/escribibles por el agente ni la API, y se ocultan del árbol de archivos.
- **`run_command` endurecido:** whitelist + patrones destructivos bloqueados (rm recursivo en cualquier orden, fork-bomb, `dd if=`, `git push --force`, format/mkfs/shutdown).
- **SSRF cerrado:** `fetch_url` bloquea IPs privadas, loopback y link-local (incl. `169.254.169.254`) y esquemas no http/https; opt-out con `SWARM_ALLOW_PRIVATE_FETCH=1`.
- **Backups a prueba de traversal:** bucket nombrado por hash SHA-1 de la ruta absoluta, con nombres únicos garantizados.
- **Sandbox Docker** (`SWARM_SANDBOX=docker`): contenedor efímero con `--cap-drop ALL`, `--network none`, `--security-opt no-new-privileges`, `--read-only`, `--user 1000:1000`, `--pids-limit`, `--cpus`.
- **RBAC:** roles ordenados viewer < editor < owner; modo local single-user = owner implícito.

---

## 9. Frontend (componentes)

`frontend/app/page.tsx` (UI principal) + `frontend/components/`:

| Componente | Función |
|---|---|
| `MonacoEditor.tsx` | Editor de código (motor de VS Code) |
| `FileExplorer.tsx` | Árbol de archivos del proyecto |
| `Terminal.tsx` | Terminal integrada (WebSocket PTY) |
| `OutputConsole.tsx` | Consola de salida / streaming de eventos del agente |
| `AgentPanel.tsx` | Panel del agente (estado, plan, coste) |
| `ApprovalModal.tsx` | Confirmación de acciones de riesgo |

Cliente REST + SSE en `frontend/lib/api.ts`; tipos en `frontend/types/index.ts`.

---

## 10. Calidad y verificación

- **Suite de tests:** 55 tests en 5 archivos:
  - `test_core.py`, `test_router.py`, `test_security.py`, `test_phases.py`, `test_platform.py`.
  - Cubren: routing/fallback, precios/coste, detector de bucles, auth/RBAC, SSRF, comandos bloqueados, filesystem seguro, persistencia, sandbox endurecido, cola de trabajos, tenancy/cuotas, retrieval, scheduling del enjambre, checkpoints, grafo de dependencias, métricas y evals.
  - Ejecución: `cd backend && python -m pytest`.
- **Arnés de evals** (`app/evals/`): asserts de tipo `file_exists`/`contains`, `command_succeeds`, `no_secret_leak`. Se omite sin claves.
- **CI** (`.github/workflows/ci.yml`): ruff + pytest + evals + `tsc --noEmit`.

---

## 11. Configuración (variables de entorno, `.env`)

| Variable | Defecto | Uso |
|---|---|---|
| `PROJECT_ROOT` | — | Carpeta de trabajo del agente (aquí: `…/swarm-ide/projects/current`) |
| `SWARM_HOST` | `127.0.0.1` | Host de enlace; `0.0.0.0` para LAN (requiere token) |
| `SWARM_PORT` | `8000` | Puerto del backend |
| `SWARM_AUTH_TOKEN` | — | Secreto compartido; **obligatorio** si no es loopback |
| `SWARM_CORS_ORIGINS` | `localhost:3000` | Orígenes CORS permitidos |
| `SWARM_ALLOW_PRIVATE_FETCH` | `0` | `1` permite `fetch_url` a IPs privadas |
| `SWARM_SANDBOX` | `local` | `local` \| `docker` \| `auto` |
| `SWARM_DB` | SQLite | `postgres` + `DATABASE_URL` para Postgres |
| `SWARM_SECRET` | — | Habilita emisión de tokens auth/RBAC |
| `NEXT_PUBLIC_SWARM_TOKEN` | — | Token en el frontend (o `localStorage.swarm_token`) |
| 8× claves de proveedor | — | `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `GROQ_API_KEY`, `GLM_API_KEY`, `GEMINI_API_KEY`, `DEEPSEEK_API_KEY`, `HF_TOKEN`, `OPENROUTER_API_KEY` |

---

## 12. Puesta en marcha (Windows)

```
1. INSTALAR.bat   ← solo la primera vez (crea venv, pip install, npm install)
2. INICIAR.bat    ← arranca backend (:8000) + frontend (:3000) y abre el navegador
3. PARAR.bat      ← detiene ambos procesos
```

- **INSTALAR.bat** comprueba Python/Node/Git, crea el entorno virtual, instala dependencias de backend y frontend y crea `projects/current`.
- **INICIAR.bat** lanza `_run_backend.bat` (uvicorn) y `_run_frontend.bat` (`npm run dev`) en ventanas separadas, espera la compilación de Next.js y abre `http://localhost:3000`.
- **Modo plataforma:** `docker compose up` (Postgres + Redis + API); imagen de sandbox con `make sandbox-image`.

### Estado de la instalación verificada en este equipo (8 jun 2026)
- Python 3.10.11, Node 24.12.0 / npm 11.6.2, Git 2.52.0 — **presentes**.
- `backend/venv` y `frontend/node_modules` — **instalados**.
- `.env` con las 8 claves API — **configurado**.
- Backend respondiendo `HTTP 200` en `/ready` (`127.0.0.1:8000`).
- Frontend respondiendo `HTTP 200` en `:3000`, título *"Crystal Swarm IDE — Final Chronicles"*.

---

## 13. Documentación de referencia del proyecto

- `README.md` — guía de uso e inicio rápido.
- `CHANGELOG.md` — historial de versiones (v4.0 → v5.1).
- `ARCHITECTURE.md` — detalle de arquitectura y modos de despliegue.
- `ROADMAP.md` — fases, esfuerzos y dependencias.
- `AUDITORIA.md` — hallazgos de seguridad resueltos en v4.0.
- `.env.example` — todas las variables de entorno.

---

*Documento generado automáticamente a partir del estado real del código y del entorno. Cualquier cifra (líneas, módulos, endpoints) proviene de inspección directa del repositorio.*
