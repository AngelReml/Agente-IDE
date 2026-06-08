# Roadmap — Swarm IDE: del local-first al IDE agéntico de plataforma

**Fecha:** 8 de junio de 2026
**Punto de partida:** v4.0 (local-first endurecido — ver `CHANGELOG.md`).
**Destino:** plataforma de IDE agéntico multi-tenant con enjambre real, comparable a la
generación Antigravity / Cursor-agent, **sin perder** el modo local de un clic.

> ### 🟢 Estado v5.1 — todas las fases a profundidad construible (55 tests en verde)
> Cada fase está implementada hasta donde se puede **construir y verificar** sin desplegar infra:
> **Q** prompt externo + evals + CI · **1** sandbox Docker endurecido (cap-drop, network none, no-root,
> read-only) + preflight · **2** cola de trabajos (in-process + Arq/Redis) + worker + runs durables ·
> **3** tenancy real (users/workspaces/roles/cuotas/audit + confinamiento de FS) · **4** enjambre
> paralelo (planner→DAG→batches) + retrieval TF-IDF + gate de revisión con reintento · **5**
> checkpoints de workspace + grafo de dependencias + agentes en segundo plano · **6** métricas
> Prometheus + request-id + `/ready`. Ver `CHANGELOG.md` (v5.1) y `ARCHITECTURE.md`.
>
> **Lo único que falta es aprovisionamiento de infraestructura, no código:** arrancar Firecracker/
> gVisor para tenants no confiables, un clúster Redis con N workers, Postgres gestionado, un servidor
> LSP y un índice de embeddings real, y el despliegue k8s. El código que los consume ya existe, con
> interfaces estables y fallback local.

---

## 1. Norte y supuestos

**Visión.** Un desarrollador (o un equipo) describe un objetivo y un *enjambre* de agentes
especializados planifica, edita en paralelo a lo largo de todo el repo, ejecuta y repara sus
propios tests, y entrega un PR revisado — de forma segura, observable y con coste acotado.
Funciona igual en tu portátil que en un servidor compartido.

**Supuestos de planificación** (ajústalos si cambian):

- **Equipo:** 2–4 ingenieros + diseño parcial. Las estimaciones son para ese tamaño.
- **Modelo de despliegue objetivo:** *self-hostable* (Docker Compose para empezar, Kubernetes
  para escalar), con capacidad multi-tenant. No asumimos SaaS público desde el día 1, pero
  cada decisión lo deja abierto.
- **Local-first es sagrado:** el `INICIAR.bat` de un clic debe seguir funcionando en cada fase.
  La plataforma es un superconjunto, no un reemplazo.
- **Reuso máximo de v4.0:** `tools.py`, `safe_fs.py`, `smart_router.py`, `cost_tracker.py`,
  `ast_indexer.py` y `security.py` se conservan como **librerías**; lo que se reescribe es la
  capa de *orquestación y operación*, no las capacidades.

**No-goals (acotar para no morir de alcance):** no construiremos nuestros propios modelos, ni
un editor desde cero (seguimos sobre Monaco), ni un clon pixel-perfect de ningún producto.

---

## 2. Principios de diseño

1. **Seguridad antes que features.** Nada multiusuario se expone sin aislamiento de ejecución
   real (Fase 1 bloquea a las demás en cualquier despliegue compartido).
2. **Estado fuera del proceso.** Todo lo que v4.0 dejó en memoria/SQLite migra a un backend de
   estado externo para poder escalar horizontalmente.
3. **El run es un trabajo, no una request.** Desacoplar ejecución de la conexión HTTP es lo que
   da durabilidad, reanudación y paralelismo.
4. **Evals como red de seguridad.** Cada mejora de agente se mide contra un set de tareas; sin
   esto, "mejorar el enjambre" es adivinar.
5. **Coste como ciudadano de primera.** El contador de v4.0 se convierte en presupuestos y
   límites por usuario/equipo/tarea.

---

## 3. Mapa de fases (resumen)

| Fase | Objetivo | Esfuerzo | Depende de | Valor desbloqueado |
|------|----------|----------|-----------|--------------------|
| **0** | Local-first endurecido | ✅ hecho (v4.0) | — | Base segura y testeada |
| **Q** | Quick wins pre-plataforma | S (1–2 sem) | 0 | Telemetría, evals mínimas, editor inline |
| **1** | Aislamiento de ejecución | L (4–6 sem) | 0 | Seguridad para cualquier despliegue compartido |
| **2** | Persistencia + cola de trabajos | L (4–6 sem) | 0 | Durabilidad, reanudación, escala horizontal |
| **3** | Multiusuario / multi-tenant | XL (6–8 sem) | 1, 2 | Equipos, cuotas, aislamiento de datos |
| **4** | Enjambre real (paralelo) | XL (8–10 sem) | 2 | Calidad en tareas grandes, planner+review gate |
| **5** | Capacidades de IDE agéntico | XL (10–14 sem, continuo) | 2, 4 | Paridad con la categoría de referencia |
| **6** | Operación / SRE | M (transversal) | 1–5 | Observabilidad, fiabilidad, cumplimiento |

Esfuerzo: S≈1–2 sem · M≈3–4 sem · L≈4–6 sem · XL≈8–14 sem. Con solapamiento, el total realista
es **~9–12 meses**.

---

## 4. Fase Q — Quick wins (antes del gran salto)

Cosas de alto valor y bajo coste que no requieren rediseño y que preparan el terreno.

- **Observabilidad del agente** (tracing de cada paso/tool con OpenTelemetry o LangSmith) — sin
  esto, depurar el enjambre futuro será a ciegas.
- **Arnés de evals mínimo:** 15–30 tareas de referencia con asserts (compila, pasa tests, hace
  el cambio pedido) ejecutables en CI. Reusa la suite `backend/tests` como semilla.
- **Editor inline (Monaco):** ghost-text y diff por hunks con aceptar/rechazar; conecta el
  `apply_patch` ya existente a la UI.
- **Externalizar el prompt del sistema** a fichero versionado + versionado de prompts (cierra Q3
  de la auditoría del todo).
- **CI/CD:** GitHub Actions con `ruff` + `pytest` + `tsc --noEmit` + el arnés de evals.

**Criterio de hecho:** cada PR corre lint + tests + evals; un cambio del agente puede medirse.

---

## 5. Fase 1 — Aislamiento de ejecución

**Objetivo.** Que tools, `run_command` y la terminal se ejecuten **dentro de un sandbox por
workspace**, nunca sobre el host. Es el prerrequisito de todo despliegue compartido (sin esto,
S1–S3 de la auditoría reaparecen amplificados).

**Entregables**

- Ejecutor de comandos/tools en contenedor por workspace (un volumen montado = el proyecto).
- Filesystem confinado al workspace; sin alcance al disco del host.
- Límites de recursos (CPU, RAM, PIDs), timeouts e idle-shutdown del sandbox.
- Política de egress de red por allowlist (refuerza el guard SSRF a nivel de kernel/red).
- Terminal PTY dentro del sandbox.

**Decisiones técnicas (build-vs-buy)**

| Necesidad | Recomendado | Alternativas | Por qué |
|-----------|-------------|--------------|---------|
| Aislamiento | **Docker + perfil seccomp/AppArmor** para empezar | gVisor (más seguro), Firecracker microVM (máximo aislamiento, más complejo) | Docker es el camino más corto a "suficientemente seguro"; gVisor/Firecracker se adoptan en Fase 3 si hay tenants no confiables |
| Sistema de archivos | Volumen por workspace + overlay | Bind-mount restringido | Aísla y permite snapshots |
| Red | iptables/allowlist por contenedor | Proxy egress | Defensa en profundidad sobre el guard SSRF |

**Reuso de v4.0:** `safe_fs` y `security.blocked_command`/`validate_outbound_url` siguen como
capa lógica; el sandbox es la capa física que faltaba.

**Riesgos / mitigación:** rendimiento de arranque del sandbox (mitiga con pool de contenedores
calientes); compatibilidad Windows local (mantén el modo "sin sandbox" para el `INICIAR.bat`).

**Criterio de hecho:** un agente malicioso no puede leer/escribir fuera de su workspace ni
alcanzar la red privada; verificado con un set de tests de escape.

---

## 6. Fase 2 — Persistencia y cola de trabajos

**Objetivo.** Convertir el "run = request SSE" en "run = trabajo durable". Es lo que rompe el
techo de v4.0 (estado en proceso) y habilita escala horizontal y reanudación.

**Entregables**

- **Postgres**: usuarios, sesiones, workspaces, runs, mensajes, eventos, coste (migra `store.py`).
- **Redis**: cola de trabajos + pub/sub para fan-out de eventos a SSE/WebSocket.
- **Pool de workers** (Arq/Celery/RQ) que ejecuta los runs; la API solo encola y hace streaming.
- Runs **reanudables y cancelables**; reconexión de SSE sin perder el run si el cliente cae.
- Historial de runs con replay de eventos (extiende `/api/runs` ya existente).

**Decisiones técnicas**

| Necesidad | Recomendado | Alternativas | Por qué |
|-----------|-------------|--------------|---------|
| Cola | **Arq** (async, Redis nativo) | Celery (maduro), RQ (simple) | Encaja con el stack async de FastAPI/LangGraph |
| Estado | **Postgres** | SQLite (solo local), MySQL | Concurrencia real, JSONB para eventos |
| Pub/sub SSE | **Redis Streams** | NATS | Reaprovecha Redis de la cola |

**Reuso de v4.0:** el esquema de `store.py` (runs/events) se promueve casi tal cual a Postgres;
`graph.run_swarm_stream` pasa a ser el cuerpo del worker en vez del handler HTTP.

**Riesgos:** complejidad operativa (mitiga con Docker Compose para dev); coherencia de eventos
(usa IDs monótonos por run, ya presentes).

**Criterio de hecho:** matar el backend a mitad de un run no lo pierde; el cliente reconecta y
ve el run continuar/completarse.

---

## 7. Fase 3 — Multiusuario / multi-tenant

**Objetivo.** Varios usuarios/equipos sobre la misma instancia, con aislamiento de datos,
secretos y presupuesto.

**Entregables**

- **AuthN**: OAuth/OIDC (Google/GitHub) + sesiones + API keys de servicio.
- **AuthZ**: RBAC por workspace/organización (owner/editor/viewer).
- **Aislamiento por tenant**: datos en Postgres con scoping por org; filesystem por workspace
  (Fase 1); secretos en un **vault** (no en `.env` compartido).
- **Cuotas y rate-limiting** por usuario/org sobre tokens y coste (extiende `cost_tracker`).
- **BYO-key vs claves gestionadas**: cada org puede traer sus claves o consumir un pool con
  presupuesto.
- **Audit log** de acciones del agente (qué tocó, quién lo lanzó).

**Decisiones técnicas**

| Necesidad | Recomendado | Alternativas | Por qué |
|-----------|-------------|--------------|---------|
| Auth | **Authentik/Keycloak** (self-host) o Auth0 | propio | No reinventar identidad |
| Secretos | **HashiCorp Vault** o sops + KMS | env cifrado | Rotación y scoping por tenant |
| Aislamiento datos | RLS de Postgres por org | esquemas por tenant | Simple y auditable |

**Riesgos:** superficie de seguridad (mitiga con security reviews por fase, ya tienes el skill
`/security-review`); complejidad de cuotas (empieza con límites duros, refina después).

**Criterio de hecho:** un tenant no puede ver ni tocar datos/claves/workspaces de otro;
verificado con tests de aislamiento y un pentest básico.

---

## 8. Fase 4 — Enjambre real (orquestación multi-agente paralela)

**Objetivo.** Honrar el nombre: pasar de un agente ReAct + 2 subagentes secuenciales a un
**planner + ejecutores especializados en paralelo** con revisión que puede **bloquear**.

**Entregables**

- **Planner-Executor**: un planner descompone el objetivo en un **DAG** de subtareas con
  dependencias (reusa y eleva `update_plan`).
- **Agentes especializados en paralelo** (Arquitecto, Coder, Revisor, Tester) como nodos de un
  grafo LangGraph con `asyncio.gather`; los subagentes ya son async desde v4.0 (C6).
- **Gate de revisión**: el Revisor puede **rechazar** un cambio y devolverlo al Coder (hoy
  `delegate_review` se ignora salvo que el LLM decida leerlo).
- **Pizarra compartida** (blackboard) de estado entre agentes; contexto *scoped* por agente.
- **Retrieval sobre el repo** (índice de embeddings + grafo de símbolos/dependencias) para que
  cada agente reciba solo el contexto relevante — supera el volcado de `list_files`.
- **Convergencia y presupuesto**: el planner respeta un presupuesto de tokens/coste por tarea
  (atado al `cost_tracker`), con votación/criterio de parada.

**Decisiones técnicas**

| Necesidad | Recomendado | Alternativas | Por qué |
|-----------|-------------|--------------|---------|
| Orquestación | **LangGraph multi-nodo** | crew/autogen | Ya estás sobre LangGraph |
| Retrieval | **Índice de embeddings** (pgvector) + grafo AST (extiende `ast_indexer`) | grep puro | Contexto preciso = mejor calidad/coste |
| Memoria entre agentes | Blackboard en Redis/Postgres | en proceso | Sobrevive y es inspeccionable |

**Riesgos:** explosión de coste (mitiga con presupuestos por tarea y modelos baratos para roles
auxiliares, ya soportado por el routing fast/power); bucles entre agentes (reusa y generaliza el
`LoopDetector`).

**Criterio de hecho:** en tareas multi-archivo del set de evals, el enjambre supera al agente
único en tasa de éxito (tests verdes) a coste comparable o con mejora de calidad medible.

---

## 9. Fase 5 — Capacidades de IDE agéntico de referencia

**Objetivo.** Cerrar la brecha funcional con la categoría (Antigravity/Cursor-agent).

**Entregables (priorizados)**

- **Comprensión profunda del repo:** integración LSP (definiciones, referencias, tipos) + grafo
  de dependencias, además del índice semántico actual.
- **Edición agéntica a escala con auto-reparación:** bucles de verificación (edita → `run_tests`
  → si falla, lee el error y corrige), generación de tests, refactors multi-archivo con
  `apply_patch`.
- **Agentes en segundo plano:** tareas largas/programadas (reusa el patrón de tareas
  programadas), que abren PRs cuando terminan.
- **Editor inline maduro:** ghost-text, diffs por hunk, "explicar selección", "arreglar este
  error".
- **Agente de navegador/preview:** levantar el preview, e2e, capturas y *walkthroughs* (artefactos
  visuales del trabajo hecho).
- **Checkpoints / time-travel de todo el workspace** (no solo backup por archivo como hoy).
- **Sistema de plugins/MCP + integraciones:** GitHub PRs, CI, issue trackers, Slack.

**Riesgos:** alcance enorme (por eso es continuo y priorizado por evals/uso, no de golpe).

**Criterio de hecho:** un usuario puede pedir "implementa esta issue", el sistema abre un PR con
código + tests verdes + descripción, revisable y con checkpoint para revertir.

---

## 10. Fase 6 — Operación / SRE (transversal)

**Objetivo.** Que la plataforma sea fiable, observable y operable.

**Entregables**

- **Observabilidad:** tracing de pasos del agente (OpenTelemetry/LangSmith), métricas
  (Prometheus/Grafana), logs estructurados con request/run IDs.
- **Evals de regresión** en CI como gate de calidad del agente; guardrails de salida.
- **Despliegue:** Kubernetes con autoscaling de workers, secretos gestionados, backups y DR.
- **Controles de abuso y cumplimiento:** rate-limiting, retención de datos, base para SOC2.

**Criterio de hecho:** SLO definidos (disponibilidad, latencia de arranque de run), alertas, y un
runbook de incidentes.

---

## 11. Secuenciación y dependencias

```
Fase 0 (v4.0 ✅)
  └─> Fase Q (quick wins) ──────────────┐
        ├─> Fase 1 (aislamiento) ───┐    │
        └─> Fase 2 (cola/estado) ───┼────┼─> Fase 4 (enjambre) ─> Fase 5 (capacidades)
                                     │    │            ▲
              Fase 1 + Fase 2 ───────┴────┴─> Fase 3 (multi-tenant)
                                                        
        Fase 6 (operación) ── transversal, empieza en Q y crece con cada fase
```

- **1 y 2 son paralelizables** y juntas habilitan la 3.
- **2 habilita la 4** (el enjambre necesita estado/cola para correr agentes en paralelo durables).
- **4 alimenta la 5** (las capacidades avanzadas se apoyan en el enjambre + retrieval).
- **3 es independiente de 4**: puedes tener multi-tenant con agente único, o enjambre en single-tenant.

**Timeline orientativo (equipo de 2–4, con solapamiento):**

| Mes | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9 | 10 | 11 | 12 |
|-----|---|---|---|---|---|---|---|---|---|----|----|----|
| Q   | ██ | | | | | | | | | | | |
| 1   | | ██ | ██ | | | | | | | | | |
| 2   | | ██ | ██ | | | | | | | | | |
| 3   | | | | ██ | ██ | ██ | | | | | | |
| 4   | | | | | ██ | ██ | ██ | ██ | | | | |
| 5   | | | | | | | | ██ | ██ | ██ | ██ | ██ |
| 6   | ░░ | ░░ | ░░ | ░░ | ░░ | ░░ | ░░ | ░░ | ░░ | ░░ | ░░ | ░░ |

---

## 12. Registro de riesgos transversales

| Riesgo | Prob. | Impacto | Mitigación |
|--------|-------|---------|------------|
| Coste de inferencia se dispara con el enjambre | Alta | Alto | Presupuestos por tarea, roles auxiliares en modelos baratos, caching de contexto |
| Brecha de seguridad en multi-tenant | Media | Crítico | Aislamiento físico (Fase 1) antes de exponer; security reviews por fase; pentest |
| Alcance de la Fase 5 se vuelve infinito | Alta | Medio | Priorización por evals/uso; entregar incrementos, no "todo o nada" |
| Calidad del agente regresiona al iterar | Media | Alto | Arnés de evals en CI como gate (Fase Q) |
| Complejidad operativa frena al equipo | Media | Medio | Docker Compose en dev; k8s solo al escalar; IaC desde el principio |
| Romper el modo local-first | Baja | Alto | El sandbox y la cola son opt-in; `INICIAR.bat` mantiene el camino sin dependencias |

---

## 13. Métricas de éxito (KPIs)

- **Calidad del agente:** % de tareas del eval con tests verdes al primer intento (Fase Q baseline → sube con Fase 4).
- **Éxito multi-archivo:** tasa de éxito en tareas que tocan 3+ archivos (enjambre vs agente único).
- **Coste por tarea resuelta** (USD) — debe bajar o mantenerse al mejorar calidad.
- **Durabilidad:** % de runs que sobreviven a un reinicio del backend (objetivo 100% tras Fase 2).
- **Aislamiento:** 0 escapes de sandbox en el set de tests de seguridad (Fase 1, Fase 3).
- **Latencia de arranque de run** (cola → primer token) y disponibilidad (Fase 6 SLO).

---

## 14. Qué reusar de v4.0 (no se tira nada)

| Componente v4.0 | Rol en la plataforma |
|-----------------|----------------------|
| `tools.py` (incl. `apply_patch`, `update_plan`, `run_tests`) | Capacidades del agente, intactas; corren dentro del sandbox |
| `safe_fs.py` | Capa lógica de FS + backups → base de los checkpoints de workspace |
| `smart_router.py` (`RouterState`, fallback completo) | Routing por agente/rol con presupuesto |
| `cost_tracker.py` | Semilla de cuotas y presupuestos por tarea/usuario |
| `ast_indexer.py` | Base del retrieval (se le suma embeddings + LSP) |
| `security.py` | Capa lógica de seguridad que el sandbox refuerza físicamente |
| `store.py` (esquema runs/events) | Se promueve a Postgres casi tal cual |
| `runtime.py` (RunContext, LoopDetector) | Estado por run/agente; el LoopDetector se generaliza al enjambre |
| Suite `backend/tests` | Semilla del arnés de evals |

---

## 15. Primer sprint recomendado (las dos próximas semanas)

1. CI con `ruff` + `pytest` + `tsc --noEmit`.
2. Arnés de evals con 15 tareas y asserts.
3. Tracing de pasos del agente (OpenTelemetry).
4. Spike de Fase 1: ejecutar `run_command` dentro de un contenedor Docker con FS confinado, como
   prueba de concepto medida.

Con eso entras a la Fase 1 con telemetría y una vara de medir — que es justo lo que faltaba para
construir el enjambre sin volar a ciegas.
