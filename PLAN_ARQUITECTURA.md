# Plan de arquitectura — Swarm IDE (post-auditoría)

> Fecha: 9 jun 2026. Estado de partida: tras 9 oleadas de arreglos (`audit-1…9`),
> los fallos están resueltos. Quedan **3 cambios de arquitectura mayores** que la
> auditoría señaló como "camino de producción". Este documento es el plan para
> ejecutarlos con seguridad, por fases, cada una entregable y verificable.
>
> Principios: (1) cada fase deja el sistema funcionando; (2) nada rompe el modo
> local de un clic; (3) cada cambio llega con tests; (4) feature-flags para
> activar/desactivar sin reescribir.

Orden recomendado por riesgo/dependencia:
**A. Aislamiento por sesión** (base de concurrencia) → **B. Retrieval con embeddings**
(independiente) → **C. Socket-proxy / sandbox de producción** (solo afecta despliegue).

Esfuerzos: 🟢 bajo (~1-2 días) · 🟡 medio (~3-5 días) · 🔴 alto (~1-2 semanas).

---

## A. Aislamiento total por sesión 🟡

### Problema (hallazgos A1, A2 de la auditoría)
Varias piezas de estado son **globales de proceso**, así que dos sesiones/pestañas
concurrentes se pisan:
- `smart_router._routing_mode` y `_manual_model_id` (modo y modelo manual globales).
- `graph._session_messages` (historial de chat global — una conversación pisa otra).
- `state_context` (singleton de archivos modificados; `reset_session` de una sesión
  borra el tracking de otra).
- `cost_tracker._session` / `_last_run` (coste agregado de todas las sesiones).

Hoy está **mitigado** (locks + purga + `RunContext`/`Session` ya existen en
`runtime.py`), pero el estado no se **consume** por sesión: el router sigue leyendo
los globales y `graph` la lista global.

### Diseño objetivo
Una única fuente de verdad por sesión: extender `runtime.Session` para que **posea
todo** el estado mutable, y que `graph`/`orchestrator`/`smart_router` reciban la
sesión en vez de leer módulos globales.

```
Session (runtime.py)
├── routing_mode, manual_model        # ya existen → empezar a USARLOS
├── messages: list[BaseMessage]       # mover aquí _session_messages
├── modified_files / changelog_added  # mover aquí el estado de state_context
└── cost: SessionCost                 # acumulador por sesión (no global)
```

### Pasos
1. **Router por estado, no global** (🟢):
   - `graph.run_swarm_stream` y `orchestrator` ya crean `RouterState(mode=…, start_model_id=…)`.
     Pasar `session.routing_mode` y `session.manual_model` desde `SESSIONS.get(session_id)`
     en lugar de `get_routing_mode()`/`consume_manual_model()` globales.
   - Endpoints `/api/routing/mode` y `/api/models/select` pasan a aceptar `session_id`
     y escribir en la `Session`, no en los globales del módulo.
   - Mantener los globales solo como *default* para llamadas sin sesión (compat).
2. **Historial por sesión** (🟡): mover `_session_messages` a `Session.messages`;
   `store.load/save_history_raw` pasa a estar **keyed por session_id** (hoy es un
   único `session_history.json`; usar `session_history/<sid>.json` o una tabla).
   `_update_session_history` opera sobre la sesión activa del run.
3. **State Guard por sesión** (🟡): `state_context` pasa de singleton a `dict[sid]`
   bajo lock (ya tiene el lock entre hilos; falta la clave de sesión). `graph`
   resetea/consulta el sub-estado de SU sesión.
4. **Coste por sesión** (🟢): añadir `SessionCost` a `Session`; `/api/cost?session_id=…`
   devuelve el de esa sesión. Mantener un total global opcional para `/metrics`.
5. **Limpieza**: el `SessionManager` ya purga sesiones inactivas (hecho en audit-4);
   asegurar que purgar una sesión libera su historial/estado.

### Tests
- Dos `RouterState`/sesiones concurrentes con modos distintos no se interfieren.
- Historial de sesión A no aparece en sesión B (test con dos session_id).
- State Guard reporta solo los archivos de su sesión.
- Regresión: el modo single-sesión (default) se comporta igual que hoy.

### Riesgos
- Cambia la firma de varios endpoints/funciones → hacerlo retrocompatible (session_id
  opcional, default "default"). El frontend ya manda `session_id` por pestaña.

---

## B. Retrieval con embeddings (semántico) 🟡

### Problema (hallazgo M10 + límite de calidad)
`retrieval.py` usa **TF-IDF** (léxico): no entiende sinónimos ni semántica, y el
chunking es por líneas fijas. Ya está **cacheado** (audit-8), pero la *calidad* del
contexto que recibe el enjambre está limitada a coincidencia de palabras.

### Diseño objetivo
Interfaz `Retriever` con dos implementaciones intercambiables por flag
(`SWARM_RETRIEVAL=tfidf|embeddings`), para no romper el modo offline:
- **TF-IDF** (actual, sin dependencias, default offline).
- **Embeddings**: chunking por símbolos (reutilizar `ast_indexer` para cortar por
  función/clase, no por líneas), embeddings con un proveedor barato
  (p. ej. `text-embedding-3-small` de OpenAI o local con `sentence-transformers`),
  y búsqueda por similitud coseno. Persistencia del índice vectorial:
  - **Local**: índice en SQLite/`.swarm` (numpy + coseno en memoria) — sin infra.
  - **Plataforma**: `pgvector` sobre el Postgres que ya está en `docker-compose`.

```
retrieval.Retriever (interfaz: add(), query(), build_for_repo())
├── TfidfRetriever        (hoy)
└── EmbeddingRetriever    (nuevo)
     ├── chunk: ast_indexer → bloques por símbolo + ventana
     ├── embed: provider (OpenAI / local) con caché por hash de chunk
     └── store: NumpyStore (local) | PgVectorStore (plataforma)
```

### Pasos
1. **Refactor a interfaz** (🟢): extraer `Retriever` (protocolo) y dejar TF-IDF como
   una implementación. `retrieve_context` selecciona por flag. (No cambia el default.)
2. **Chunking semántico** (🟢): función que use `ast_indexer` para cortar por
   función/clase con solapamiento; fallback a líneas para archivos no indexables.
3. **Capa de embeddings** (🟡): `embed_texts(texts) -> list[vector]` con caché por
   `sha1(chunk)` en `.swarm/embeddings/` para no re-embeddear lo no cambiado
   (reutiliza la firma de cambios de audit-8). Coste controlado y medible vía
   `cost_tracker`.
4. **Almacén vectorial** (🟡): `NumpyStore` local (matriz + coseno, suficiente hasta
   ~10⁴ chunks) y `PgVectorStore` para plataforma (índice IVFFlat/HNSW).
5. **Invalidación incremental**: re-embeddear solo los chunks cuyos archivos cambiaron
   (mtime/size), igual que la caché actual.
6. **Evals** (🟢): añadir al arnés de `app/evals` un set de consultas con el chunk
   esperado, para medir *recall@k* TF-IDF vs embeddings y no regresionar.

### Tests / aceptación
- `EmbeddingRetriever` con un mock de embeddings (vectores deterministas) rankea el
  chunk relevante primero (igual estilo que `test_tfidf_ranks_relevant_chunk_first`).
- Caché: no re-embeddea si el repo no cambió; sí lo hace si un archivo cambia.
- Flag a `tfidf` reproduce el comportamiento actual exacto.

### Riesgos
- Coste/latencia de embeddings → mitigado con caché agresiva y modelo barato; el
  modo local por defecto sigue siendo TF-IDF (sin coste, offline).
- `pgvector` requiere extensión en Postgres → solo en el camino plataforma.

---

## C. Socket-proxy / sandbox de producción 🔴

### Problema (hallazgo A7/C2)
`docker-compose` monta `/var/run/docker.sock` en el contenedor de la API. Aunque ya
lo pusimos en **solo-lectura** y la API es **no-root** (audit-6), el acceso al socket
del daemon sigue siendo, en la práctica, control casi total del host. Para
multi-tenant real el ejecutor del agente necesita aislamiento fuerte.

### Diseño objetivo (defensa en capas, elegir según necesidad)
1. **Socket-proxy con allowlist** (paso 1, 🟡): interponer
   `tecnativa/docker-socket-proxy` entre la API y el daemon, permitiendo solo los
   endpoints que `DockerBackend` usa (crear/arrancar/borrar contenedores efímeros,
   logs), y **denegando** el resto (exec arbitrario, montajes del host, swarm, etc.).
   La API habla con `tcp://docker-proxy:2375`, nunca con el socket crudo.
2. **Runtime aislado por contenedor** (paso 2, 🔴): ejecutar cada comando del agente
   en un contenedor con runtime endurecido:
   - **gVisor** (`runsc`): kernel en espacio de usuario, bajo coste, buen aislamiento.
   - **Sysbox**: contenedores "como VM" sin privilegios.
   - **Firecracker/Kata**: microVMs, aislamiento máximo (mayor coste). Para el nivel
     más alto de multi-tenant no confiable.
   `DockerBackend.build_args` ya está endurecido (`--cap-drop ALL`, `--network none`,
   `--read-only`, `no-new-privileges`, `--pids-limit`, `--cpus`); añadir `--runtime=runsc`
   por flag (`SWARM_SANDBOX_RUNTIME`).
3. **Sin socket en la API** (paso 3, 🔴): mover la ejecución a un **worker dedicado**
   (el `worker.py`/Arq que ya existe) que es el único con acceso al proxy; la API
   nunca toca Docker. Encaja con el camino "runs durables vía cola" ya esbozado.

### Pasos
1. Añadir servicio `docker-proxy` al `docker-compose` con allowlist mínima; la API
   usa `DOCKER_HOST=tcp://docker-proxy:2375`. Quitar el mount del socket de la API.
2. `platform/sandbox.py`: `DockerBackend` lee `DOCKER_HOST`/`SWARM_SANDBOX_RUNTIME`;
   `preflight()` valida la conexión al proxy y la disponibilidad del runtime.
3. Cuota de recursos por workspace (CPU/mem/pids/tiempo) leída de `tenancy` (las
   cuotas de coste ya existen; añadir límites de ejecución).
4. Mover la ejecución al worker out-of-process; la API solo encola.
5. **Hardening de red**: por defecto `--network none`; egress solo vía un proxy
   con allowlist si una tarea lo necesita.

### Tests / aceptación
- `build_args` incluye `--runtime` cuando el flag está activo (test puro, como el
  actual `test_docker_args_are_hardened`).
- Preflight falla de forma clara si el proxy/runtime no está disponible (no degrada
  en silencio — coherente con la política fail-fast de audit-6).
- Prueba de humo: un comando malicioso (`rm -rf /`, acceso a `/host`) queda confinado.

### Riesgos
- gVisor/Firecracker añaden latencia de arranque y complejidad operativa → empezar
  por socket-proxy (gran parte del riesgo eliminado con poco esfuerzo) y subir nivel
  según el modelo de amenaza.
- Solo afecta al **despliegue plataforma**; el modo local de un clic no cambia.

---

## Secuenciación y entregables

| Fase | Workstream | Esfuerzo | Estado | Entregable verificable |
|------|------------|----------|--------|------------------------|
| 1 | A1 — router/coste por sesión | 🟢 | ✅ | 2 sesiones concurrentes aisladas (test) |
| 2 | A2 — historial/State Guard por sesión | 🟡 | ✅ | sin cross-talk entre pestañas (test) |
| 3 | B1 — interfaz Retriever + chunking AST | 🟢 | ✅ | flag tfidf↔embeddings, default igual |
| 4 | B2 — embeddings + caché + store local | 🟡 | ✅ | recall@k mejor en evals, offline intacto |
| 5 | C1 — socket-proxy + DOCKER_HOST | 🟡 | ✅ | API sin socket crudo; proxy con allowlist |
| 6 | C2 — runtime aislado (gVisor) + cuotas | 🔴 | ◑ | runtime por flag + cuotas/workspace (falta worker out-of-process) |
| 7 | B3 — pgvector (plataforma) | 🟡 | ✅ | retrieval escalado sobre el Postgres existente |

Cada fase: rama propia, tests nuevos, feature-flag, y el modo local de un clic
**nunca se rompe**. Total estimado: ~3-5 semanas de trabajo enfocado.

### Estado a 9 jun 2026
Fases 1–5 y 7 **completas**; Fase 6 **parcial** (◑): `--runtime` endurecido por
`SWARM_SANDBOX_RUNTIME` y cuotas de recursos por workspace (`tenancy.limits_for`)
están hechas y testeadas; queda el paso 4 (mover la ejecución del sandbox a un
worker out-of-process para que la API solo encole). Suite: 98 tests en verde.

Flags introducidos: `SWARM_SANDBOX_RUNTIME`, `DOCKER_HOST`, `SWARM_SANDBOX_CPUS`,
`SWARM_SANDBOX_PIDS`, `SWARM_VECTOR_STORE` (memory|pgvector), `SWARM_EMBED_DIM`.

## Qué NO cambia
El arranque local (`INICIAR.bat`), la experiencia de un solo usuario, y los valores
por defecto (TF-IDF offline, sandbox local en loopback) siguen igual. Todo lo de este
plan es **opt-in** por flag o solo afecta al despliegue multi-tenant.
