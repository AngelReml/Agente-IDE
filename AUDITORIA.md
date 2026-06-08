# Auditoría técnica — Swarm IDE v3.0

> ## ✅ DOCUMENTO SUPERADO — Resuelto en v4.0 (8 jun 2026)
> Esta auditoría se realizó sobre **v3.0**. **Todos** los hallazgos críticos, altos,
> medios y de limpieza han sido **corregidos, mejorados y ampliados** en la versión
> **v4.0**. Ver `CHANGELOG.md` para el detalle por hallazgo y la **tabla de estado de
> resolución** al final de este documento (§7). El backend se reescribió en gran parte
> (estado por sesión, persistencia SQLite, seguridad por capas, fallback completo) y se
> añadió una suite de **22 tests en verde**. Se conserva el análisis original abajo como
> registro histórico.

**Fecha:** 8 de junio de 2026
**Alcance:** backend (`backend/app/*`), frontend (`frontend/*`), scripts de arranque y configuración.
**Tamaño revisado:** ~6.000 líneas (≈3.000 Python, ≈3.000 TypeScript/TSX).
**Método:** lectura completa de cada módulo, trazado del flujo de datos extremo a extremo y verificación cruzada de los hallazgos de mayor impacto contra el código.

---

## 1. Veredicto ejecutivo

Swarm IDE es un proyecto **notablemente competente para su categoría**: un IDE multi-agente local, sin Docker, con streaming SSE, fallback entre 24 modelos de 8 proveedores, editor Monaco, terminal por WebSocket, timeline de backups e indexador AST. La calidad de la capa de presentación es alta y la idea de producto está bien ejecutada. Funciona y se siente pulido.

Dicho esto, como **producto local de un solo usuario está bien; como base para escalar a algo multiusuario o expuesto, su techo es bajo** y se topa con tres muros estructurales: (1) un modelo de seguridad que asume confianza total y que en la configuración por defecto queda expuesto a toda la red local, (2) estado global mutable de proceso único que impide cualquier concurrencia, y (3) un "enjambre" que en realidad es un único agente ReAct con dos subagentes síncronos, sin paralelismo real.

La buena noticia: casi todos los problemas son **acotados y corregibles** sin reescribir el núcleo. Abajo el detalle, ordenado por severidad y con justificación.

**Resumen de hallazgos:** 4 críticos · 9 altos · 12 medios · 10 bajos/limpieza.

---

## 2. Catálogo de hallazgos

Severidad: 🔴 Crítico · 🟠 Alto · 🟡 Medio · ⚪ Bajo/limpieza.

### 2.1 Seguridad

| # | Sev | Hallazgo | Evidencia | Impacto |
|---|-----|----------|-----------|---------|
| S1 | 🔴 | **RCE sin autenticación expuesto a la LAN.** El backend arranca con `uvicorn --host 0.0.0.0`, CORS `allow_origins=["*"]`, sin ninguna autenticación, y el endpoint `/ws/terminal` ejecuta **comandos arbitrarios** vía PowerShell/bash **sin whitelist ni patrones bloqueados** (a diferencia de la tool `run_command`). | `_run_backend.bat:7`; `main.py:33-38`; `terminal.py:30-52,148-150` | Cualquier dispositivo de la red (Wi-Fi compartida, hotspot, oficina) puede abrir `ws://IP:8000/ws/terminal` y ejecutar código como el usuario. Es el riesgo nº1. |
| S2 | 🔴 | **Acceso total al sistema de archivos del PC.** `read_file`, `list_files`, `grep_search` y `get_architecture_tree` llaman a `resolve_and_validate_path(..., allow_external=True)`. El propio prompt lo declara: *"acceso completo a CUALQUIER ruta del PC"*. `write_file`/`delete_file` fuera del workspace solo exigen `overwrite_external=True` / `confirmed=True`, banderas que **el propio agente puede activar**. | `tools.py:104-147,511-549`; `graph.py:128-131` | El agente (o quien controle el prompt) puede leer `~/.ssh`, `.env`, navegadores, y escribir/borrar fuera del proyecto. El "confirm" no es una barrera real porque el LLM lo rellena solo. |
| S3 | 🟠 | **La whitelist de `run_command` da falsa seguridad.** Permite `python`, `pip`, `node`, `npm`, `npx`, `git`, `curl`. Cualquiera de ellos ejecuta código arbitrario: `python -c "..."`, `npm`/`git` con hooks, `pip install` desde un repo malicioso, `curl` para exfiltración. Los `BLOCKED_PATTERNS` por regex se evaden trivialmente (`rm  -rf` con tabs, `rm -r -f`, rutas con comillas). | `tools.py:34-61,346-459` | El sandboxing es cosmético. No hay aislamiento de proceso (sin contenedor, sin usuario restringido). |
| S4 | 🟠 | **SSRF en `fetch_url`.** GET a cualquier URL sin allowlist ni bloqueo de IPs privadas/link-local. | `tools.py:463-506` | El agente puede alcanzar `169.254.169.254` (metadata), routers de la intranet, paneles internos. Relevante si algún día corre en una VM/cloud. |
| S5 | 🟡 | **`.env` con secretos es visible y editable desde la UI.** `_build_tree` incluye `.env` explícitamente en el árbol, y `read_file` puede abrirlo. | `main.py:108`; `tools.py:127-147` | Las claves de 8 proveedores (todas presentes en texto plano en tu `.env`) se pueden abrir en el editor Monaco y son legibles por el agente. *Nota positiva:* `.env` sí está correctamente en `.gitignore` y **no** está trackeado por git. |
| S6 | 🟡 | **Reescritura de `.env` con `re.sub` sin escapar el reemplazo.** `switch_project` hace `re.sub(r"PROJECT_ROOT=.*", new_line, ...)` donde `new_line` proviene de la ruta del usuario. Las secuencias `\1`, `\g<...>` en la cadena de reemplazo se interpretan como backreferences. | `main.py:343-349` | Una ruta con caracteres especiales puede corromper el `.env` (aunque se convierten `\`→`/`, el reemplazo sigue sin `re.escape`). Mejor reescribir línea a línea sin regex. |
| S7 | 🟡 | **Sanitización de rutas de backup por sustitución de string.** `rel_path.replace("..","_up_").replace(":","_drive_")` para evitar fuga del directorio de backups. | `safe_fs.py:58,159` | Es frágil (no cubre todos los vectores de path traversal). Debería usarse un hash o `os.path.commonpath` validado. |

### 2.2 Concurrencia y estado (el techo de escalado)

| # | Sev | Hallazgo | Evidencia | Impacto |
|---|-----|----------|-----------|---------|
| C1 | 🟠 | **Todo el estado de ejecución es global de proceso.** El índice de modelo (`_idx`), el historial de sesión (`_session_messages`), el coste (`_run`/`_session`) y el modo de routing (`_routing_mode`) son variables de módulo. | `smart_router.py:193-200`; `graph.py:24`; `cost_tracker.py:66-67` | **Dos peticiones `/run` concurrentes se pisan** el modelo, el historial y el coste. El sistema es de facto monousuario y mono-tarea. Es el límite duro de la arquitectura. |
| C2 | 🟠 | **El "State Guard" casi con seguridad nunca se dispara (bug funcional).** Usa `ContextVar` para registrar archivos modificados, pero las tools síncronas de LangChain se ejecutan en un *threadpool* que **copia** el contexto al lanzarse; las escrituras (`add_modified_file`, `mark_changelog_added`) ocurren en el contexto hijo y **no vuelven** al generador padre que lee `get_modified_files()`. | `state_context.py:*`; `tools.py:183,244`; `graph.py:179-189,319-321` | La advertencia *"N archivos modificados sin actualizar memoria.md"* probablemente no se emite nunca. La feature está rota en silencio. |
| C3 | 🟠 | **En modo "fast" se rompe el fallback automático.** `reset_for_run()` posiciona `_idx` en el primer modelo barato (p. ej. Groq, índice 5). `advance()` **solo avanza a índices mayores**. Anthropic/OpenAI (índices 0–4) quedan *por debajo* y **nunca se intentan como respaldo**, aunque haya clave. | `smart_router.py:262-276,284-292` | Contradice la promesa del README (*"avanza automáticamente si el modelo activo falla"* / *"Never stops"*). Si fallan los baratos+gratuitos, declara *"Todos los modelos agotados"* sin probar los potentes disponibles. |
| C4 | 🟡 | **`PROJECT_ROOT` se captura en *import-time* y se duplica.** `tools.py` y `safe_fs.py` leen `os.getenv("PROJECT_ROOT")` cada uno por separado al importarse. El cambio de proyecto "en caliente" no surte efecto sin reiniciar (lo admite la propia respuesta: *"Restart backend to apply"*), pero la UI invita a recargar. Además ambos módulos pueden divergir. | `tools.py:21-24`; `safe_fs.py:9-12`; `main.py:353` | "Cambio de proyecto en caliente" es engañoso: medio funciona (lecturas vía `PROJECT_ROOT` viejo) y confunde al usuario. |
| C5 | 🟡 | **El historial de sesión apunta al proyecto equivocado tras cambiar de proyecto.** `_HISTORY_FILE` se fija a `PROJECT_ROOT/.swarm/...` en import-time y `_session_messages` es global, así que el contexto se mezcla entre proyectos. | `graph.py:28,83-91` | Riesgo de "fuga" de contexto de un proyecto a otro. |
| C6 | 🟡 | **Subagentes síncronos bloquean el event loop.** `delegate_research`/`delegate_review` y `diff_parser` usan `model.invoke()` **síncrono** dentro de tools llamadas desde un flujo async. | `subagents.py:34-43,65-75`; `diff_parser.py:61` | Durante una llamada al subagente el servidor no procesa nada más. No hay paralelismo real de agentes; el "swarm" es secuencial. |

### 2.3 Corrección (bugs)

| # | Sev | Hallazgo | Evidencia | Impacto |
|---|-----|----------|-----------|---------|
| B1 | 🟠 | **Detector de bucles ingenuo.** Solo compara con la llamada *inmediatamente* anterior (`_last_key`). Un patrón alterno `A,B,A,B…` no se detecta nunca, y un `read_file` legítimo repetido 6× aborta la tarea. Se reinicia por cada modelo. | `graph.py:98-116,285-299` | Falsos negativos (bucles reales A/B/A/B) y falsos positivos (repetición legítima). |
| B2 | 🟠 | **El coste de Gemini 2.5 se contabiliza como $0.** La tabla de precios no contiene `gemini-2.5-flash`/`gemini-2.5-pro` (que sí están en el chain), y sí contiene modelos que no están en el chain (`o1`, `mixtral`, `gemini-1.5`, `llama-3.1-70b`). | `cost_tracker.py:15-51` vs `smart_router.py:172-173` | El contador de coste —una feature destacada— subcontabiliza. `_price()` devuelve `(0,0)` para los modelos no listados. |
| B3 | 🟡 | **`sessionCost` en el frontend no acumula.** Hace `setSessionCost(prev => Math.max(prev, cost_usd))` sobre el coste de *un* run; nunca lee `session_stats()` del backend (que sí acumula). | `page.tsx:307-310` | El "Gil de sesión" muestra el máximo de un run, no el total. Métrica incorrecta de cara al usuario. |
| B4 | 🟡 | **Vertical slice de "diff summary" muerto/incompleto.** `fetchDiffSummary` se exporta pero **nunca se importa**; el endpoint `/api/diff/summary` y `diff_parser.generate_human_summary` **nunca se invocan** desde el front. Las River Cards leen `card.summary` pero solo se togglea `loadingSummary`; `summary` no se asigna jamás. | `api.ts:254`; `page.tsx:265-292` (nunca setea `summary`) | Las "Pergaminos Alterados" siempre muestran *"Pergamino alterado"*, sin resumen, sin +/- líneas, sin nivel de riesgo. Feature a medias y código muerto end-to-end. |
| B5 | 🟡 | **`is_high_risk_change` se llama y se descarta.** En `write_file` su resultado va a un `if ...: pass`. | `tools.py:155-158` | Lógica inútil; la "consulta obligatoria a memoria.md" no se aplica realmente. |
| B6 | ⚪ | **`was_memoria_read()` nunca se consulta.** Se marca al leer `memoria.md` pero el guard solo mira `was_changelog_added`. | `state_context.py:42-43`; `graph.py:183` | Estado muerto. |
| B7 | ⚪ | **Terminal: fusión de chunks puede entrelazar prompt y salida.** Cada frame WS se fusiona con la última línea renderizada. | `Terminal.tsx:83-94` | Glitches visuales menores en salidas rápidas. |

### 2.4 Código muerto, duplicado e inútil

| # | Sev | Hallazgo | Evidencia |
|---|-----|----------|-----------|
| D1 | ⚪ | `gitpython==3.1.43` en `requirements.txt` **nunca se importa** (todo git es `subprocess`). Dependencia muerta. | `requirements.txt:9` |
| D2 | ⚪ | `get_heavy_model()` definido y **nunca usado**. | `smart_router.py:340-347` |
| D3 | ⚪ | Tools `preview_changes` y `restore_file` en `ALL_TOOLS` pero **no mencionadas en el prompt ni usadas** por el front (la restauración real va por REST + AgentPanel). Superficie de ataque/confusión sin retorno. | `tools.py:306-342,699-723` |
| D4 | ⚪ | Endpoint `/api/index/rebuild` sin consumidor en el frontend. | `main.py:301-306` |
| D5 | ⚪ | Conjuntos de proveedores **duplicados**: `_CHEAP_PROVIDERS`/`_POWER_PROVIDERS` (l.202-203) y `_HEAVY_PROVIDERS`/`_CHEAP_PROVIDERS`/`_FREE_PROVIDERS` (l.317-319). `SKIP_DIRS` duplicado en `tools.py` y `ast_indexer.py`. Helper `_git` duplicado en `main.py` y `tools.py`. | varios |
| D6 | ⚪ | `diff_out` devuelto por `write_file_safe` se captura y descarta en todos los llamadores. | `tools.py:161,232`; `safe_fs.py:121` |

### 2.5 Calidad, mantenibilidad y operación

| # | Sev | Hallazgo |
|---|-----|----------|
| Q1 | 🟡 | **Sin tests reales.** `test_models.py` es un smoke test de conectividad, no pruebas unitarias. No hay CI, ni linter/formatter configurado, ni `mypy`. Cero red de seguridad para refactors. |
| Q2 | 🟡 | **`except Exception: pass` por todas partes** (backups, historial, coste, save_history). Silencia fallos que deberían al menos loguearse; dificulta el diagnóstico. |
| Q3 | 🟡 | **Prompt del sistema gigante hardcodeado** en `graph.py` (≈45 líneas). Imposible versionarlo, hacer A/B o adaptarlo por proyecto sin tocar código. |
| Q4 | ⚪ | **Mezcla de idiomas** (español/inglés) en código, comentarios, mensajes de error y nombres. Inconsistente. |
| Q5 | ⚪ | **Números mágicos** sin justificar: `recursion_limit=60`, `_MAX_HISTORY=60`, `_MAX_TOOL_CHARS=800`, caps de 100/400/50.000. |
| Q6 | ⚪ | **Import circular latente** `tools → subagents → tools`, resuelto con imports diferidos dentro de funciones. Frágil ante refactors. |
| Q7 | ⚪ | **`list_files` recorre el árbol completo** sin límite de profundidad/anchura (a diferencia de `_build_tree`, que sí limita). En repos enormes puede volcar demasiado contexto o tardar. |

---

## 3. Crítica arquitectónica

### 3.1 Lo que está bien pensado

El diseño tiene aciertos reales que conviene preservar:

La **separación por capas del backend** es limpia: `tools.py` (capacidades del agente), `safe_fs.py` (E/S con backups), `smart_router.py` (proveedores), `graph.py` (orquestación), `cost_tracker`/`memoria_manager`/`ast_indexer` (servicios transversales). Cada módulo tiene una responsabilidad identificable. El **fallback entre proveedores** es una idea de producto fuerte: convierte la fragilidad de cuotas/rate-limits de los LLM gratuitos en una experiencia continua. El **streaming SSE con parsing de eventos granular** (token, tool_start, tool_end, cost, model_switch) está bien modelado y es lo que da la sensación "viva" de la UI. Y el **timeline de backups** con restauración por timestamp es una red de seguridad genuinamente útil que muchos IDEs-IA no tienen.

El frontend, pese al exceso de estilo inline, está **correctamente componentizado** y gestiona bien los estados asíncronos (abort controllers, refs anti-stale-closure, health-check periódico, degradación elegante cuando el backend está caído).

### 3.2 Las tres fracturas estructurales

**(1) El modelo de confianza no tiene capas.** La arquitectura asume "un usuario de confianza en su propia máquina" y, sobre esa premisa, concede al agente acceso total al disco y a la shell. Eso sería defendible para una herramienta estrictamente local —si no fuera porque el arranque por defecto la publica en `0.0.0.0` sin auth. El problema no es solo el bind: es que **no existe un concepto de límite de privilegio** en ninguna capa. No hay separación entre "lo que el usuario autoriza" y "lo que el agente decide", porque las confirmaciones las rellena el propio LLM. Para cualquier escenario que no sea localhost estricto, esto es un muro.

**(2) El estado vive en variables de módulo.** Es la decisión que fija el techo. Mientras el modelo de modelo activo, historial, coste y routing sean globales de proceso, **no puede haber dos tareas a la vez, ni dos proyectos, ni dos usuarios**. Toda la lógica de `advance()`/`reset_for_run()` está escrita asumiendo un único hilo de ejecución lógico. Migrar esto a estado por sesión no es trivial pero tampoco enorme; es la inversión de mayor retorno.

**(3) El "swarm" es marketing, no arquitectura.** Hoy hay **un** agente ReAct (`create_react_agent`) con dos subagentes (`researcher`, `reviewer`) invocados de forma síncrona y bloqueante. Los "roles" (Oracle, Wizard, Scholar, Knight, Bard) del panel son **decorativos**: rotan en un `setInterval`, no corresponden a procesos reales. No hay descomposición de tareas, ni agentes paralelos, ni planificación jerárquica. Es un buen agente único; no es un enjambre. Esto está bien siempre que no se prometa lo contrario, pero limita la narrativa de escalado.

### 3.3 Deuda transversal

La ausencia de tests convierte cada uno de los bugs anteriores (B1–B7) en algo que solo se detecta en producción. El silenciamiento de excepciones (Q2) agrava esto: un backup que falla, un coste mal contabilizado o un historial corrupto no dejan rastro. Y el prompt monolítico (Q3) significa que iterar sobre el comportamiento del agente —el corazón del producto— requiere editar código Python, no configuración.

---

## 4. Análisis de techo y escalabilidad

### 4.1 ¿Dónde está el techo hoy?

El producto actual escala a: **1 usuario · 1 tarea concurrente · 1 proyecto activo · 1 máquina.** Ese es el techo duro, y lo imponen el estado global (C1) y la captura de `PROJECT_ROOT` en import-time (C4–C5), no la potencia de los modelos.

En el eje de *carga de trabajo* el límite lo marcan: el `recursion_limit=60` de LangGraph, el `_MAX_HISTORY=60` mensajes y la persistencia en un único `session_history.json`. Tareas largas o repos gigantes (donde `list_files`/`get_semantic_map` vuelcan mucho contexto) chocarán con límites de ventana de contexto antes que con límites de infraestructura.

En el eje de *robustez* el techo lo marca la inexistencia de cola/persistencia de runs: si el backend reinicia a mitad de una tarea, el run se pierde (el SSE muere con el proceso) y no hay forma de reanudarlo.

### 4.2 Hasta dónde podría llegar, y qué hace falta para cada salto

**Nivel 0 → 1 — De herramienta personal a herramienta personal *robusta* (esfuerzo bajo, 1–2 semanas).**
Sin cambiar la arquitectura: bindear a `127.0.0.1` por defecto (S1), añadir un token compartido para el WS y los endpoints mutadores, arreglar el fallback de modo fast (C3), el coste de Gemini (B2), el `sessionCost` (B3), el state guard (C2) o eliminarlo, y completar o borrar el diff-summary muerto (B4). Añadir una batería mínima de tests sobre `safe_fs`, `smart_router.advance` y `diff_parser`. Esto te deja un producto local *correcto*.

**Nivel 1 → 2 — Multi-tarea / multi-proyecto en una sola máquina (esfuerzo medio, 3–6 semanas).**
Encapsular **todo** el estado global en un objeto `Session`/`Run` identificado por id, pasado explícitamente por el flujo (no variables de módulo). `PROJECT_ROOT` pasa a ser propiedad de la sesión, leído en runtime, no en import. Esto desbloquea pestañas paralelas, varios proyectos abiertos y el cambio de proyecto en caliente *de verdad*. Sustituir `session_history.json` por SQLite (runs, mensajes, costes, backups indexados). Aquí el `advance()` debe reescribirse para recorrer *todos* los modelos disponibles con un orden de prioridad, no un índice monótono.

**Nivel 2 → 3 — Multiusuario / servidor compartido (esfuerzo alto, 2–4 meses).**
Este es el salto que la arquitectura actual **no** soporta y que exige rediseño, no parches. Hace falta: (a) **aislamiento de ejecución** real por usuario —contenedor o microVM por workspace— porque sin él S1–S3 son inaceptables fuera de localhost; (b) autenticación/autorización y multi-tenancy (cada usuario solo ve su workspace); (c) una **cola de trabajos** (Celery/RQ/Arq) que desacople el run del ciclo de vida del request, con SSE/WebSocket reconectables y reanudables; (d) backend de estado externo (Postgres + Redis) en lugar de memoria de proceso; (e) cuotas y rate-limiting por usuario sobre el coste de tokens. En la práctica esto es "reescribir la capa de orquestación y operación manteniendo `tools.py`/`safe_fs.py`/`smart_router.py` como librerías".

**Nivel 3 → 4 — Enjambre real (esfuerzo alto, ortogonal).**
Para honrar el nombre: descomponer la tarea en un planificador + agentes especializados que corran **en paralelo** (LangGraph soporta grafos multi-nodo y `asyncio.gather`), con un agente revisor que pueda *bloquear* un commit (hoy `delegate_review` se ignora salvo que el LLM decida leerlo). Convertir los subagentes síncronos en async. Esto multiplica la calidad en tareas grandes pero también el coste por tarea, así que conviene atarlo al contador de coste (ya existente) con presupuestos.

### 4.3 Veredicto sobre el techo

**El techo de la base de código *actual* es el Nivel 1–2.** Es excelente como herramienta local para un desarrollador y, con el trabajo de encapsulación de estado del Nivel 2, se vuelve un producto local sólido y multiproyecto. **Pasar de ahí (Nivel 3+) no es escalar esta arquitectura: es reescribir su columna de orquestación y operación.** La buena noticia, ya señalada, es que las *capacidades* (filesystem seguro, routing de modelos, indexación, herramientas del agente) están razonablemente bien encapsuladas y son reutilizables tal cual; lo que no escala es el *pegamento* que las orquesta. Eso acota mucho el coste del rediseño futuro.

---

## 5. Plan de acción priorizado

**Ahora (seguridad, antes de compartir la herramienta con nadie):**
1. `--host 127.0.0.1` por defecto; documentar `0.0.0.0` como opt-in consciente (S1).
2. Token compartido obligatorio en `/ws/terminal` y endpoints de escritura/borrado (S1, S2).
3. Restringir `fetch_url` (bloquear IPs privadas/link-local) (S4).
4. Reescribir la edición de `.env` sin `re.sub` con reemplazo crudo (S6).

**Siguiente (corrección de bugs visibles):**
5. Arreglar el fallback de modo fast en `advance()` (C3) — es una promesa incumplida del README.
6. Corregir la tabla de precios y alinearla con el chain (B2); leer `session_stats` real en el front (B3).
7. Arreglar o eliminar el State Guard (C2) y el diff-summary muerto (B4).
8. Endurecer el detector de bucles (ventana de N llamadas, no solo la anterior) (B1).

**Después (salud del proyecto):**
9. Tests sobre `safe_fs`, `smart_router.advance`, `diff_parser.parse_diff_stats`, `memoria_manager`; añadir CI + ruff/eslint.
10. Limpieza de código muerto y duplicado (D1–D6, B5–B6).
11. Externalizar el prompt del sistema a fichero/config (Q3).

**Estratégico (si se busca crecer):**
12. Encapsular estado global en `Session` (C1, C4, C5) — la inversión de mayor retorno.
13. Persistencia en SQLite (runs, historial, coste).
14. Si se apunta a multiusuario: aislamiento por contenedor + auth + cola de trabajos.

---

## 6. Nota positiva de cierre

Conviene insistir en algo que el catálogo de problemas tiende a ocultar: **para un proyecto de este alcance, el nivel de pulido y de detalle es alto.** El fallback entre proveedores, el timeline de backups, el streaming de eventos y la atención al detalle de la UI están por encima de lo habitual. La mayoría de los hallazgos críticos son *de configuración y de límites de confianza*, no de incompetencia de diseño, y se arreglan en días. El trabajo de fondo —encapsular estado y aislar ejecución— es exactamente el que toca hacer cuando un prototipo bueno aspira a convertirse en producto. La base es sólida; el techo solo está bajo donde todavía no se ha invertido.

---

## 7. Estado de resolución (v4.0)

Todos los hallazgos quedan cerrados. Detalle de implementación en `CHANGELOG.md`.

| ID | Hallazgo | Estado | Dónde |
|----|----------|--------|-------|
| S1 | RCE expuesto a la LAN | ✅ Resuelto | bind loopback + auth token (`config`, `security`, `main`) |
| S2 | Acceso total al filesystem | ✅ Acotado | secretos vetados, `.env` oculto |
| S3 | Whitelist de comandos débil | ✅ Endurecido | `security.blocked_command` |
| S4 | SSRF en `fetch_url` | ✅ Resuelto | `security.validate_outbound_url` |
| S5 | `.env` visible/editable | ✅ Resuelto | `SECRET_FILES` |
| S6 | Edición `.env` con regex | ✅ Resuelto | reescritura línea a línea |
| S7 | Sanitización de backups frágil | ✅ Resuelto | bucket por hash SHA-1 |
| C1 | Estado global de proceso | ✅ Resuelto | `runtime.RunContext`/`SessionManager` |
| C2 | State Guard no dispara | ✅ Resuelto | registro con lock (`state_context`) |
| C3 | Fallback roto en modo fast | ✅ Resuelto + test | `RouterState`/`build_order` |
| C4 | `PROJECT_ROOT` en import-time | ✅ Resuelto | `config.project_root()` runtime |
| C5 | Historial cruza proyectos | ✅ Resuelto | historial bajo `.swarm` del proyecto |
| C6 | Subagentes bloquean el loop | ✅ Resuelto | `asyncio.to_thread` |
| B1 | Detector de bucles ingenuo | ✅ Resuelto + test | ventana deslizante |
| B2 | Coste de Gemini 2.5 = $0 | ✅ Resuelto + test | precios alineados |
| B3 | `sessionCost` mal calculado | ✅ Resuelto | lee `/api/cost` |
| B4 | Diff-summary muerto | ✅ Resuelto | cableado `/api/git/diff` + `/api/diff/summary` |
| B5 | `is_high_risk_change` ignorado | ✅ Resuelto | aviso + sugerencia review |
| B6 | Estado muerto `was_memoria_read` | ✅ Eliminado | — |
| B7 | Merge de líneas en Terminal | ⚠️ Menor (sin cambio) | cosmético |
| D1 | `gitpython` sin usar | ✅ Eliminado | `requirements.txt` |
| D2 | `get_heavy_model` sin usar | ✅ En uso | fallback de subagentes |
| D3 | Tools muertas | ✅ Limpiado | `restore_file` tool fuera |
| D4 | `/api/index/rebuild` sin uso | ✅ Conservado | con auth (útil) |
| D5 | Constantes duplicadas | ✅ Resuelto | unificadas en `config` |
| D6 | `diff_out` descartado | ✅ Resuelto | ya no se propaga |
| Q1 | Sin tests | ✅ Resuelto | 22 tests en `backend/tests` |
| Q2 | `except: pass` masivo | ◑ Mejorado | rutas críticas con logging |
| Q3 | Prompt monolítico | ◑ Mejorado | reescrito; pendiente externalizar a fichero |
| Q4–Q7 | Calidad menor | ◑ Mejorado | límites configurables, dedupe, idioma |

### Nuevas capacidades añadidas (más allá de la auditoría)

`apply_patch` (edición multi-archivo atómica) · `update_plan`/`read_plan`
(planificación persistente estilo IDE agéntico) · `run_tests` (verificación
automática) · persistencia SQLite de runs/eventos/coste con `/api/runs` ·
multi-sesión (`session_id`). Estas acercan el Swarm IDE a la categoría de los IDE
agénticos de referencia, manteniendo la arquitectura local-first.
