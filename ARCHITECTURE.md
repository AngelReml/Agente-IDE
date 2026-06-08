# Arquitectura — Swarm IDE v5.0

Dos modos sobre la misma base de código: **local-first** (un clic, sin infra) y
**plataforma** (multi-tenant, escalable). Cada pieza degrada con elegancia: si la
infra pesada no está, se usa el backend local equivalente.

## Mapa de módulos (backend)

```
app/
├── main.py            FastAPI: REST + SSE + WebSocket. Endpoints durables y de enjambre.
├── config.py          Configuración central (host, token, sandbox, db, límites).
├── security.py        Auth de request, guard SSRF, bloqueo de comandos.
├── auth.py            [Fase 3] Tokens HMAC, principal user+workspace+rol, RBAC.
│
├── graph.py           Agente único ReAct + streaming SSE (prompt externalizado).
├── orchestrator.py    [Fase 4] Enjambre: planner → DAG → batches paralelos → review gate.
├── runmanager.py      [Fase 2] Runs durables/reconectables (buffer de eventos in-process).
├── runtime.py         Estado por run/sesión (RouterState, RunContext, LoopDetector).
│
├── smart_router.py    Chain de 24 modelos, fallback completo.
├── cost_tracker.py    Precios y coste; base de presupuestos.
├── tools.py           Herramientas del agente (fs, git, cmd, http, plan, tests, apply_patch).
├── safe_fs.py         FS seguro + backups (base de checkpoints).
├── ast_indexer.py     Índice semántico (base de retrieval).
├── memoria_manager.py Bitácora del proyecto (memoria.md).
├── state_context.py   Tracking de mutaciones (State Guard).
├── diff_parser.py     Resumen de diffs con IA.
│
├── store.py           Persistencia SQLite (runs, eventos, coste).
├── persistence.py     [Fase 2] Selector de backend: SQLite | Postgres.
├── queue.py           [Fase 2] Cola de trabajos: InProcessQueue | RedisQueue (Arq).
├── worker.py          [Fase 2] Entrypoint del worker Arq (escala out-of-process).
├── tenancy.py         [Fase 3] Users/workspaces/roles/cuotas/audit + confinamiento de FS.
├── retrieval.py       [Fase 4] Retrieval TF-IDF del repo (contexto del enjambre).
├── checkpoints.py     [Fase 5] Snapshot/restore de todo el workspace (time-travel).
├── depgraph.py        [Fase 5] Grafo de import/dependencias.
├── background.py      [Fase 5] Registro de agentes en segundo plano/programados.
├── metrics.py         [Fase 6] Métricas Prometheus + request-id.
├── telemetry.py       [Fase 6] Tracing OTel con fallback no-op.
│
├── platform/
│   └── sandbox.py     [Fase 1] Ejecución: LocalBackend | DockerBackend (endurecido).
├── prompts/system.md  [Fase Q] Prompt del sistema versionado.
├── evals/harness.py   [Fase Q] Arnés de evals con asserts.
└── tests/             55 tests (routing, seguridad, coste, fs, store, auth/RBAC, sandbox,
                       cola, tenancy, retrieval, orchestrator, checkpoints, depgraph, metrics, evals).
```

## Flujo de un run durable (Fase 2)

```
cliente ──POST /run──► main ──► RunManager.start(task)
                                   │  crea run_id, lanza tarea en segundo plano
                                   ▼
                            graph.run_swarm_stream  ──► publica eventos al buffer del run
                                   │                         │
cliente ◄──SSE (run_id + eventos)──┘                         │
   ✗ se desconecta  ── el run SIGUE ──────────────────────────┘
cliente ──GET /api/runs/{id}/stream──► RunManager.subscribe ──► replay backlog + tail
```

## Flujo de un run de enjambre (Fase 4)

```
POST /run/swarm ──► orchestrator.run_orchestrated
   1. plan(task)           → DAG de subtareas {architect, coder, reviewer, tester}
   2. schedule(subtasks)   → batches paralelos (topo-sort; detecta ciclos)
   3. por cada batch:       asyncio.gather de agentes especializados
                            eventos fusionados vía cola, etiquetados con subtask
                            blackboard comparte salidas a los dependientes
   4. review gate:          si el revisor responde ❌ RECHAZADO → se marca para revisión
```

## Ejecución de comandos (Fase 1)

`tools.run_command` → validación (whitelist + patrones bloqueados) → `sandbox.get_backend()`:

- **LocalBackend** (def.): subprocess en el host. Para uso local de confianza.
- **DockerBackend** (`SWARM_SANDBOX=docker`): contenedor efímero, `-v workspace:/workspace`,
  `--network none`, `--cap-drop ALL`, `--security-opt no-new-privileges`, usuario no-root.
  Prerrequisito de cualquier despliegue compartido.

## Modos de despliegue

| | Local-first | Plataforma |
|---|---|---|
| Arranque | `INICIAR.bat` | `docker compose up` |
| Host | `127.0.0.1` | `0.0.0.0` + token |
| Sandbox | local | docker |
| Persistencia | SQLite | Postgres |
| Auth | owner implícito | tokens + RBAC |
| Cola | in-process | Redis + workers (camino) |

## Puntos de extensión hacia producción

- **Cola distribuida:** sustituir el `RunManager` in-process por Arq/Redis (misma interfaz).
- **Multi-tenant duro:** Firecracker/gVisor por workspace; RLS en Postgres; secretos en Vault.
- **Retrieval:** sumar embeddings (pgvector) + LSP al `ast_indexer`.
- **Observabilidad:** exportador OTLP + métricas Prometheus (telemetry ya instrumentado).

Detalle de fases, esfuerzos y dependencias en `ROADMAP.md`.
