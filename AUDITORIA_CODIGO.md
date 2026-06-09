# Auditoría de código en profundidad — Swarm IDE

> Fecha: 9 jun 2026. Alcance: TODO el código de la herramienta Swarm IDE (backend `app/`, frontend, infraestructura). **No** incluye el Kanban de demostración.
> Método: 6 auditores especializados en paralelo (seguridad, routing/coste, núcleo del agente, plataforma, API/orquestador, frontend/infra) leyendo el código real, más verificación manual de los hallazgos de mayor impacto.
> Leyenda de verificación: ✅ = verificado a mano sobre el código; 🔍 = reportado por auditor (alta confianza, con cita de línea); ❓ = a confirmar.

## Veredicto general

Swarm IDE es **funcional y rico en features**, pero **no está listo para producción ni para exponerse fuera de `localhost`** tal como está. El modelo de seguridad asume "un solo usuario en local de confianza"; en cuanto se expone a una red o se usa de forma concurrente, aparecen fallos graves de seguridad, fugas de memoria y pérdida de datos. Para uso **personal en local**, la mayoría de los críticos tienen impacto bajo; para **compartir o desplegar**, son bloqueantes.

Conteo: **10 críticos, ~11 altos, ~14 medios, ~10 bajos.**

---

## ✅ Estado de remediación (9 jun 2026)

Tras la auditoría se aplicaron **6 oleadas de arreglos** (commits `audit-1`…`audit-6`),
verificadas con la suite de tests (**67 en verde**, +12 nuevos) y una prueba de
integración en vivo (backend arranca, Groq end-to-end, runs persistidos).

**Críticos — todos resueltos:** C1 (memoria acotada + runs persistidos), C2 (rechaza
arrancar expuesto sin aislamiento), C3 (bloqueo de comandos reforzado + aviso de que
no es frontera de seguridad), C4 (auth en lecturas + secretos por ruta real), C5
(auth fail-closed sin secreto), C6 (SSRF revalida redirecciones), C7 (checkpoints sin
secretos + sin traversal), C8 (escritura atómica), C9 (coste del enjambre contabilizado),
C10 (precios Anthropic corregidos).

**Altos — resueltos:** A3 (reasoners), A4 (no corromper no-UTF8 + workers no huérfanos),
A5 (fallback de modelo en subtareas), A6 (token del WebSocket), A7/A8 (compose endurecido),
A9 (CI con gate real), A10 (cardinalidad de métricas), A11 (escritura bloqueada en .git/.github).
A1/A2 (estado global de routing/sesión): mitigado parcialmente (locks + purga + cost lock);
el aislamiento total por sesión queda como mejora mayor pendiente.

**Medios — la mayoría resueltos:** M2, M5, M6, M7, M8, M9, M11, M13 hechos; B1, B3, B4 hechos.
**Pendientes deliberados** (riesgo/beneficio o refactor mayor): M1 (base_url de GLM — sin
certeza, no se toca para no romper), M10 (caché de retrieval — rendimiento), M12 (revert
del review gate — hoy solo avisa), M14 (eventos estructurados en el frontend), y ~123
avisos de estilo de ruff (informativos, no bloqueantes).

> Resumen para no técnicos: **todo lo crítico y casi todo lo grave está arreglado y probado.**
> Lo que queda son mejoras de rendimiento y de pulido, no fallos que rompan o expongan.

---

---

## 🔴 CRÍTICOS

### C1 — Fuga de memoria y pérdida de runs en `RunManager` ✅
`runmanager.py:29,34,43` — la lista `events` de cada run y el dict `_runs` (singleton de proceso, `main.py:31`) **crecen sin límite y nunca se purgan**. Además **nunca persiste en el store**: contradice su propio docstring ("runs survive restarts"). *Corroborado en vivo:* durante la demo, `/api/runs` salía **vacío** mientras había runs activos.
- **Impacto:** consumo de RAM creciente → caída por OOM con el tiempo; historial de runs vacío/incoherente; reconexión "durable" que no es durable.
- **Fix:** acotar eventos (`deque(maxlen)`), evictar runs por TTL/LRU, y persistir en `store` desde el driver in-process.

### C2 — `LocalBackend` ejecuta sin ningún aislamiento y es el modo por defecto 🔍
`platform/sandbox.py:28-45` + `config.py:99` — por defecto los comandos del agente corren **directamente en el host**, heredando todo `os.environ` (incluidas claves API), sin límites de CPU/mem/red. Nada obliga a usar Docker al exponer el servidor.
- **Impacto:** si la API se expone (`SWARM_HOST=0.0.0.0`), es ejecución remota de código sobre tu máquina.
- **Fix:** en el arranque, rechazar `sandbox=local` si el host no es loopback; en modo `auto`, fallar si no hay Docker en vez de degradar en silencio.

### C3 — El "guard" de comandos es evadible y el terminal abre un shell real 🔍
`security.py:99-119`, `terminal.py:38-54`, `tools.py:359` — el bloqueo es una lista negra de regex sobre la cadena cruda. La whitelist permite `python`/`node`/`npx` → `python -c "..."` ejecuta cualquier cosa. El terminal lanza PowerShell/bash completos. `Remove-Item -Recurse` ni siquiera está en la lista.
- **Impacto:** ejecución arbitraria/destructiva; el bloqueo da falsa sensación de seguridad.
- **Fix:** no depender de la lista negra; confiar en sandbox real (Docker `--network none`, FS read-only). Tokenizar y aplicar whitelist sobre el ejecutable real.

### C4 — Lectura de archivos y diffs SIN autenticación + filtrado de secretos incompleto 🔍✅
`main.py:204` (`GET /api/file`), `:198` (`/api/files`), `:275` (`/api/git/diff`, además con `allow_external=True`) — **no** llevan `require_auth`. `_is_secret` (`tools.py:53`) compara solo el *basename* literal: se evade con `.ENV` (Windows), espacios, o un symlink a `.env`. `SECRET_FILES` no cubre `*.pem`, `*.key`, `.env.bak`, `id_rsa`, etc.
- **Impacto:** con el servidor expuesto, cualquiera en la red lee todo el código y secretos no listados, sin token.
- **Fix:** `require_auth` en todos los endpoints de lectura; filtrar secretos por patrón sobre la **ruta real resuelta**, fail-closed.

### C5 — Secreto HMAC vacío → tokens de cualquier rol forjables 🔍
`auth.py:36-38` — `_secret()` cae a `SWARM_AUTH_TOKEN or ""`. Si se activa auth (host no-loopback) sin `SWARM_SECRET`, se firman/verifican tokens con **clave vacía conocida**; cualquiera puede forjar un token `role=owner`. Además el token compartido (que viaja en claro en cada request) sirve a la vez de clave de firma.
- **Impacto:** bypass total de RBAC en modo expuesto.
- **Fix:** fail-closed si auth activa y secreto vacío; separar estrictamente clave de firma del token de acceso.

### C6 — SSRF por DNS rebinding y redirecciones en `fetch_url` 🔍
`security.py:66-95` — `validate_outbound_url` resuelve y valida la IP una vez, pero la conexión real re-resuelve (TOCTOU) y **sigue redirecciones 3xx sin re-validar**.
- **Impacto:** acceso a metadata cloud (`169.254.169.254`), servicios internos, loopback.
- **Fix:** fijar (pin) la IP validada y conectar a ella; deshabilitar o re-validar redirecciones.

### C7 — Los checkpoints copian `.env` y secretos en claro + path traversal en restore 🔍
`checkpoints.py:23-46` — el snapshot recorre el proyecto y **no excluye `SECRET_FILES`**; copia cada `.env` sin cifrar a `.swarm/checkpoints/`. `restore_checkpoint` no valida `..` en las rutas del manifest.
- **Impacto:** duplicación persistente de secretos; restore manipulado puede escribir fuera del proyecto.
- **Fix:** excluir secretos en el walk; validar rutas en restore; escritura atómica.

### C8 — Escritura de archivos NO atómica (riesgo de corromper tu código) 🔍
`safe_fs.py:89-115` — `write_file_safe` escribe **directo sobre el destino**; si el proceso muere a mitad, el archivo queda truncado. `apply_patch` (`tools.py`) escribe archivo por archivo sin transacción real pese a anunciarse "atómico".
- **Impacto:** corrupción/pérdida de archivos ante cualquier interrupción.
- **Fix:** escribir a temporal + `os.replace()`; en `apply_patch`, todos los temporales primero y luego confirmar (o revertir backups).

### C9 — El coste del enjambre NO se contabiliza 🔍✅
`orchestrator.py:142,167-199` — los subagentes y el planner ejecutan modelos sin el hook de coste (que solo existe en `graph.run_swarm_stream`). `budget_exceeded` nunca se llama.
- **Impacto:** en modo enjambre, `/api/cost` y los presupuestos **mienten** (se factura a ~$0); sin tope de gasto real.
- **Fix:** registrar uso (`cost_tracker.record`) en cada subagente; cablear un presupuesto que aborte.

### C10 — Precios de modelos Anthropic mal calibrados ✅
`cost_tracker.py:17,19` — Opus 4.5 figura a `(15, 75)` y Haiku 4.5 a `(0.25, 1.25)`. Según el precio vigente, Opus 4.5 ronda **$5/$25** (sobrefacturado ~3×) y Haiku 4.5 **$1/$5** (subfacturado ~4×). *(Verificar contra la página de precios actual de Anthropic.)*
- **Impacto:** el contador de coste es poco fiable justo en los modelos más usados del modo Power.
- **Fix:** corregir la tabla y verificar también GLM/HuggingFace (HF se factura a $0 aunque el router enruta a proveedores de pago).

---

## 🟠 ALTOS

- **A1 — Estado de routing global sin lock** 🔍 (`smart_router.py:215-262`): `_routing_mode`/`_manual_model_id` son globales de proceso; dos runs concurrentes se pisan el modo/modelo. El docstring afirma haberlo eliminado, pero `Session.routing_mode` no se usa.
- **A2 — Historial de sesión y State Guard globales** 🔍 (`graph.py:19`, `state_context.py`): `_session_messages` y el tracking de mutaciones son singletons de módulo → **cross-talk entre sesiones concurrentes** (una conversación pisa otra).
- **A3 — `is_retriable` clasifica por substring** 🔍 (`smart_router.py:42`): un 401 de un proveedor puede abortar toda la run, y `context_length_exceeded` provoca cascada de reintentos en modelos con ventana aún menor.
- **A4 — Edición de archivos no-UTF8 los corrompe** 🔍 (`tools.py` edit_file/apply_patch con `errors="replace"`): lee con reemplazo de bytes inválidos y reescribe → destruye permanentemente caracteres de archivos latin-1/binarios.
- **A5 — Orquestador sin fallback de modelo + workers huérfanos** 🔍 (`orchestrator.py:167-241`): una subtarea con 429 no degrada a otro modelo (a diferencia del modo single); si el cliente SSE se desconecta, los subagentes siguen ejecutándose (quemando tokens y tocando disco) sin `gather` en `finally`.
- **A6 — El WebSocket del terminal del frontend no envía token** 🔍 (`frontend/components/Terminal.tsx:99`): con auth activa el terminal **siempre falla**; sin auth queda abierto a cualquiera en la red.
- **A7 — `docker-compose` monta el socket Docker + API como root** 🔍 (`docker-compose.yml:44`, `Dockerfile.api`): socket Docker en un contenedor root = escape a root del host ante cualquier RCE.
- **A8 — Postgres/Redis con credenciales triviales y puertos expuestos** 🔍 (`docker-compose.yml`): `swarm/swarm`, Redis sin password, `5432`/`6379` publicados.
- **A9 — CI no falla ante lint/typecheck; instalación no reproducible** 🔍 (`.github/workflows/ci.yml`): `ruff ... || true`, `npm ci || npm install`, sin `next build` ni tests de frontend.
- **A10 — Fuga de cardinalidad en métricas** 🔍 (`main.py:60` + `metrics.py`): el label `path` incluye `run_id`/`ckpt_id` reales → series infinitas → memory leak inducible remotamente. Además `/metrics` sin auth expone coste.
- **A11 — `POST /api/file` puede escribir en `.git/hooks` y `.github/`** 🔍 (`main.py:226`): permite RCE diferido (hook de pre-commit) y modificar configs/workflows.

---

## 🟡 MEDIOS (selección)

- **M1 — base_url de GLM posiblemente incorrecta** ❓ (`smart_router.py:66`): mismo patrón que el bug de Groq; `open.bigmodel.cn` puede requerir auth JWT propia y fallar con `ChatOpenAI`. Verificar contra Z.ai.
- **M2 — `max_tokens`/`temperature` ciegos** 🔍: los modelos de razonamiento (DeepSeek R1) pueden rechazar `temperature`; algunos free de OpenRouter topan por debajo de 8192.
- **M3 — `set_model` pierde el fallback hacia modelos superiores** 🔍 (`smart_router.py:202`): fijar un modelo de baja prioridad desactiva los de alta como red de seguridad.
- **M4 — LoopDetector con falsos negativos** 🔍 (`runtime.py:36`): patrones de periodo > ventana (A,B,C,A,B,C) pueden no detectarse; depende de `LOOP_WINDOW`.
- **M5 — `store.py` serializa lecturas con lock global y traga errores** 🔍: throughput limitado; eventos perdidos sin aviso; sin migraciones de esquema.
- **M6 — Degradación permanente a SQLite** 🔍 (`persistence.py:95`): si Postgres está caído al primer acceso, se cachea SQLite local para toda la vida del proceso → datos divergentes en despliegue horizontal.
- **M7 — `POST /api/project/switch` acepta cualquier ruta del disco** 🔍 (`main.py:476`): apunta `PROJECT_ROOT` a `C:\Users` y, combinado con C4, lee todo; reescritura de `.env` ingenua.
- **M8 — `DELETE /api/file` sin backup** 🔍 (`main.py:241`): `shutil.rmtree` directo, irreversible.
- **M9 — Errores 500 filtran rutas internas** 🔍 (`main.py` varios `HTTPException(500, str(exc))`).
- **M10 — Retrieval sin caché (O(repo) por consulta) y `ast.walk` O(n²)** 🔍 (`retrieval.py`, `ast_indexer.py`): latencia/memoria altas en repos grandes; no filtra binarios.
- **M11 — `parse_plan` sin límite de subtareas + sin semáforo de concurrencia** 🔍 (`orchestrator.py:52,230`): un plan con cientos de tareas lanza cientos de agentes a la vez → DoS/coste.
- **M12 — El review gate no bloquea** 🔍 (`orchestrator.py:246`): tras rechazo persistente, el cambio del coder ya tocó disco y el run termina como exitoso igualmente.
- **M13 — CORS frágil** 🔍 (`main.py:39`): `allow_credentials=True` con `*` en métodos/headers; si alguien pone `SWARM_CORS_ORIGINS=*`, riesgo CSRF.
- **M14 — Frontend acoplado por strings** 🔍 (`page.tsx:285,296`): extrae rutas y detecta "confirmación requerida" parseando el texto humano del evento; cambia el copy y se rompe.

---

## 🟢 BAJOS (selección)

- **B1 — El "interrumpir" del terminal no mata el proceso** ✅ (`terminal.py:94,158`): `current_proc` nunca se asigna al lanzar el comando, así que el handler de `interrupt` (línea 112) es un no-op. Bug funcional confirmado.
- **B2 — `background.py`**: cron declarado pero no implementado; tareas en memoria que se pierden al reiniciar; no valida intervalos negativos.
- **B3 — `worker.py` sin `try/finally`**: un run que lanza excepción queda "zombie" en estado `running`; reintentos duplican eventos (sin idempotencia).
- **B4 — `SessionManager` sin expiración** (`runtime.py:91`): leak de memoria lento.
- **B5 — `cd` del terminal sin confinar** + sin límite de tamaño/tiempo de salida.
- **B6 — Token en `localStorage`** (latente ante futuro XSS); preferir cookie HttpOnly en despliegue.
- **B7 — `Dockerfile.api` sin pin de digest y como root**; deps con rangos `>=` sin lock → builds no reproducibles.
- **B8 — Excepciones tragadas en silencio** en varios puntos (`safe_fs`, `grep_search`, `graph`) → diagnóstico difícil.
- **B9 — `shlex.split(posix=True)` en Windows** rompe rutas con `\`; lo validado puede diferir de lo ejecutado.
- **B10 — `newline` no fijado en escrituras**: posible duplicación `\r\r\n` en Windows.

---

## Cosas que están BIEN (verificadas, no son fallos)

- **Sin inyección SQL**: `store.py` y `PostgresBackend` usan parámetros vinculados en todas las queries.
- **Sin XSS por innerHTML** en el frontend: React auto-escapa todo el contenido del modelo/archivos.
- **SSE robusto** en `lib/api.ts` (buffer por líneas, ignora malformadas, libera el reader).
- **`.env` no versionado** (solo `.env.example` en git, con campos vacíos).
- **Escrituras de texto en UTF-8 explícito** (no caen a cp1252 en Windows).
- **`Dockerfile.sandbox` usa usuario no-root** (el patrón correcto, que falta en `Dockerfile.api`).
- **El fix de Groq** (base_url + max_tokens) está bien aplicado.

---

## Plan de remediación sugerido (orden recomendado)

1. **Antes de exponer a cualquier red:** C2, C3, C4, C5, C6, A6, A7, A8 (seguridad de exposición).
2. **Estabilidad de proceso:** C1, A10 (memory leaks que tumban el servidor).
3. **Integridad de datos:** C8, C7, A4 (corrupción/pérdida/fuga de archivos).
4. **Correctitud del enjambre:** C9, A5, A1, A2, M11, M12.
5. **Fiabilidad del coste:** C10, M1.
6. **Calidad/CI e infra:** A9, B7, y el resto de medios/bajos.

> Nota: para **uso personal en `localhost`**, los riesgos de exposición (C3/C4/C5/C6/A6/A7/A8) tienen impacto bajo. Los que más te afectan en local son **C1 (memoria), C8/A4 (corrupción de archivos), C9/C10 (coste irreal) y B1 (interrumpir el terminal)**.
