# Swarm IDE v5.0

IDE multi-agente que escribe código por ti. Describe lo que necesitas en lenguaje natural y el agente (único o en **enjambre paralelo**) planifica, analiza el proyecto, crea y edita archivos (incluso de forma multi-archivo atómica), ejecuta tests, hace commit y te informa en tiempo real de cada paso.

**Local-first: corre con un clic en Windows, sin Docker.** Y escala a plataforma multi-tenant cuando lo necesitas.

> **v5.0** — cimientos de plataforma: ejecutor sandbox (Docker/local), runs durables y reconectables, persistencia pluggable (SQLite/Postgres), auth + RBAC, orquestador de enjambre paralelo, evals + CI. Construido sobre v4.0 (seguridad por capas, fallback de 24 modelos). Ver `CHANGELOG.md`, `ROADMAP.md` y `ARCHITECTURE.md`.

---

## Características principales

- **Multi-proveedor** — chain de 24 modelos en 8 proveedores con fallback automático
- **Routing inteligente** — modo ⚡ Fast (Groq/GLM, barato y rápido) o 🔥 Power (Anthropic/OpenAI, máxima calidad)
- **Streaming SSE** — cada acción del agente se muestra en tiempo real
- **Editor Monaco** — el mismo editor de VS Code, en el navegador
- **Terminal integrada** — WebSocket PTY nativo (PowerShell en Windows)
- **Contador de coste** — tokens y USD por ejecución y por sesión
- **Timeline de backups** — restaura cualquier archivo a cualquier versión anterior
- **Historial de sesión** — el agente recuerda el contexto entre cambios de modelo
- **Cambio de proyecto en caliente** — aplicado en runtime, sin reiniciar el backend
- **Detección de bucles** — ventana deslizante; avisa a las 3 repeticiones, aborta a las 6
- **Planificación del agente** — checklist persistente (`update_plan`) estilo IDE agéntico
- **Verificación automática** — `run_tests` (pytest/npm) antes de cada commit
- **Edición multi-archivo atómica** — `apply_patch` valida todo antes de escribir nada
- **Persistencia** — runs, eventos y coste en SQLite; sobreviven a reinicios
- **Seguridad por capas** — loopback por defecto, token para exposición en LAN, SSRF y secretos protegidos

---

## Inicio rápido (Windows)

```
1. Doble clic en INSTALAR.bat    ← solo la primera vez
2. Doble clic en INICIAR.bat     ← abre el IDE
3. Navega a http://localhost:3000
```

Para parar: doble clic en `PARAR.bat`.

---

## Inicio manual

**Backend:**
```bash
cd backend
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

**Frontend:**
```bash
cd frontend
npm install
npm run dev
```

---

## Variables de entorno (`.env` en la raíz)

```env
# ── Proyecto ──────────────────────────────────────────────────────────────────
PROJECT_ROOT=C:/Users/TU_USUARIO/Desktop/mi-proyecto   # carpeta de trabajo del agente

# ── Proveedores (añade solo los que tengas) ───────────────────────────────────
ANTHROPIC_API_KEY=sk-ant-...      # Claude Opus/Sonnet/Haiku  ← recomendado
OPENAI_API_KEY=sk-...             # GPT-4o / GPT-4o Mini
GROQ_API_KEY=gsk_...              # Llama 3.3 70B (gratis hasta cuota)
GLM_API_KEY=...                   # GLM-4 Plus/Air/Flash (ZhipuAI)
GEMINI_API_KEY=AIza...            # Gemini 2.5 Flash/Pro (Google AI Studio)
DEEPSEEK_API_KEY=sk-...           # DeepSeek V3 / R1
HF_TOKEN=hf_...                   # Qwen2.5, Llama 3.3 (HuggingFace)
OPENROUTER_API_KEY=sk-or-v1-...   # acceso a todos los modelos vía OpenRouter
```

Con al menos **una** clave el IDE funciona. Cada proveedor que añadas amplía el chain de fallback.

### Configuración del servidor (opcional)

```env
SWARM_HOST=127.0.0.1            # loopback por defecto. 0.0.0.0 para exponer en la LAN
SWARM_PORT=8000
SWARM_AUTH_TOKEN=               # secreto compartido. OBLIGATORIO si SWARM_HOST no es loopback
SWARM_CORS_ORIGINS=             # orígenes permitidos (coma-separados); por defecto localhost:3000
SWARM_ALLOW_PRIVATE_FETCH=0     # 1 permite que fetch_url alcance IPs privadas (desactivado por seguridad)
```

**Importante:** si expones el backend fuera de `localhost` (`SWARM_HOST=0.0.0.0`), define
`SWARM_AUTH_TOKEN` y pásalo en el frontend con `NEXT_PUBLIC_SWARM_TOKEN` (o en el navegador
con `localStorage.setItem('swarm_token', '<token>')`). Sin token, los endpoints de
escritura/ejecución quedan bloqueados.

---

## Chain de modelos (orden de prioridad)

El agente empieza en el modelo apropiado según el modo de routing y avanza automáticamente si hay error de cuota, rate-limit o saldo insuficiente.

| # | Proveedor | Modelo | Clave env |
|---|-----------|--------|-----------|
| 1 | Anthropic | Claude Opus 4.5 | `ANTHROPIC_API_KEY` |
| 2 | Anthropic | Claude Sonnet 4.5 | `ANTHROPIC_API_KEY` |
| 3 | Anthropic | Claude Haiku 4.5 | `ANTHROPIC_API_KEY` |
| 4 | OpenAI | GPT-4o | `OPENAI_API_KEY` |
| 5 | OpenAI | GPT-4o Mini | `OPENAI_API_KEY` |
| 6 | Groq | Llama 3.3 70B | `GROQ_API_KEY` |
| 7 | Groq | Llama 3.1 8B | `GROQ_API_KEY` |
| 8 | GLM | GLM-4 Plus | `GLM_API_KEY` |
| 9 | GLM | GLM-4 Air | `GLM_API_KEY` |
| 10 | GLM | GLM-4 Flash | `GLM_API_KEY` |
| 11 | Gemini | Gemini 2.5 Flash | `GEMINI_API_KEY` |
| 12 | Gemini | Gemini 2.5 Pro | `GEMINI_API_KEY` |
| 13 | Gemini | Gemini 2.0 Flash | `GEMINI_API_KEY` |
| 14 | DeepSeek | DeepSeek V3 | `DEEPSEEK_API_KEY` |
| 15 | DeepSeek | DeepSeek R1 | `DEEPSEEK_API_KEY` |
| 16 | HuggingFace | Qwen2.5 Coder 32B | `HF_TOKEN` |
| 17 | HuggingFace | Qwen2.5 72B | `HF_TOKEN` |
| 18 | HuggingFace | Llama 3.3 70B | `HF_TOKEN` |
| 19 | OpenRouter | Claude Sonnet [OR] | `OPENROUTER_API_KEY` |
| 20 | OpenRouter | Gemini 2.5 Pro [OR] | `OPENROUTER_API_KEY` |
| 21 | OpenRouter | Qwen3 235B [OR] | `OPENROUTER_API_KEY` |
| 22 | OpenRouter | Llama 3.3 Free | `OPENROUTER_API_KEY` |
| 23 | OpenRouter | Llama 3.2 3B Free | `OPENROUTER_API_KEY` |
| 24 | OpenRouter | Gemma 3 4B Free | `OPENROUTER_API_KEY` |

---

## Modos de routing

| Modo | Inicio en | Ideal para |
|------|-----------|-----------|
| ⚡ **Fast** | Groq → GLM → DeepSeek → HuggingFace | tareas simples, bajo coste |
| 🔥 **Power** | Anthropic → OpenAI → Gemini | tareas complejas, máxima calidad |

Se cambia con el toggle ⚡/🔥 junto a la caja de texto. El agente avanza automáticamente si el modelo activo falla.

---

## Herramientas del agente

| Herramienta | Descripción |
|-------------|-------------|
| `read_file` | Lee cualquier archivo del proyecto (secretos protegidos) |
| `write_file` | Crea o sobreescribe un archivo |
| `edit_file` | Edición quirúrgica (sustituye fragmento exacto) |
| `apply_patch` | Edición multi-archivo/multi-hunk **atómica** (valida antes de escribir) |
| `update_plan` / `read_plan` | Checklist persistente de la tarea |
| `run_tests` | Autodetecta y ejecuta pytest o npm test |
| `list_files` | Lista el contenido de una carpeta |
| `grep_search` / `get_semantic_map` | Búsqueda de texto y mapa semántico (AST) |
| `run_command` | Ejecuta comandos (pip, npm, pytest, ruff…) |
| `fetch_url` | GET HTTP (con protección SSRF) |
| `delegate_research` / `delegate_review` | Subagentes async (investigación / code review) |
| `git_*` | Status, diff, commit, log, branch, push |

---

## Atajos de teclado

| Acción | Tecla |
|--------|-------|
| Ejecutar tarea | `Enter` |
| Nueva línea en el input | `Shift+Enter` o `Alt+Enter` |
| Guardar archivo | `Ctrl+S` |
| Formatear código | `Ctrl+Shift+F` |

---

## Arquitectura

```
swarm-ide/
├── backend/
│   ├── app/
│   │   ├── main.py          # FastAPI — endpoints REST + WebSocket terminal
│   │   ├── config.py        # Configuración central (host, token, límites, constantes)
│   │   ├── security.py      # Auth, guard SSRF, bloqueo de comandos destructivos
│   │   ├── graph.py         # LangGraph — agente ReAct con streaming SSE
│   │   ├── runtime.py       # Estado por sesión/run (RouterState, RunContext, loop)
│   │   ├── store.py         # Persistencia SQLite (runs, eventos, coste, historial)
│   │   ├── smart_router.py  # Chain de 24 modelos, routing, fallback completo
│   │   ├── tools.py         # Herramientas del agente (fs, git, cmd, http, plan, tests)
│   │   ├── terminal.py      # WebSocket PTY nativo (con guard de comandos)
│   │   ├── cost_tracker.py  # Precios y coste USD (alineado con el chain)
│   │   ├── safe_fs.py       # Filesystem seguro + backups por hash
│   │   ├── state_context.py # Tracking de mutaciones (State Guard)
│   │   ├── diff_parser.py   # Resumen de diffs con IA
│   │   └── ast_indexer.py   # Índice semántico del proyecto
│   ├── tests/               # Suite pytest (routing, seguridad, coste, fs, store…)
│   ├── requirements.txt
│   └── test_models.py       # Test rápido de los 24 modelos
├── frontend/
│   ├── app/page.tsx         # UI principal
│   ├── components/          # Monaco, FileExplorer, Terminal, OutputConsole…
│   ├── lib/api.ts           # Cliente REST + SSE
│   └── types/index.ts
├── .env                     # Claves API (NO se sube a git)
├── INICIAR.bat
├── INSTALAR.bat
└── PARAR.bat
```

---

## Test de modelos

Verifica qué modelos tienes activos con:

```bash
cd backend
python test_models.py
```

Muestra latencia y estado (OK / FAIL / SIN CLAVE) para los 24 modelos del chain.

---

## Modo plataforma (opcional)

El modo local de un clic no necesita nada de esto. Para escalar a multi-tenant:

```bash
docker compose up        # Postgres + Redis + API
```

Capacidades v5.0:

- **Enjambre paralelo** — toggle 🐝 en la UI, o `POST /run/swarm` (planner → DAG → agentes en paralelo → revisión).
- **Runs durables** — desconéctate y reconecta sin perder el run: `GET /api/runs/{id}/stream`, `POST /api/runs/{id}/cancel`.
- **Sandbox** — `SWARM_SANDBOX=docker` ejecuta cada comando en un contenedor efímero, sin acceso al host. Construye la imagen con `make sandbox-image`.
- **Persistencia** — `SWARM_DB=postgres` + `DATABASE_URL` (si no, SQLite local).
- **Auth/RBAC** — define `SWARM_SECRET` y emite tokens con `POST /api/auth/token` (roles viewer/editor/owner).

Ver `ARCHITECTURE.md` para el detalle y `.env.example` para todas las variables.

## Tests

La suite unitaria (55 tests) cubre routing/fallback, precios, bucles, auth/RBAC, SSRF, comandos,
filesystem seguro, persistencia, sandbox endurecido, cola de trabajos, tenancy/cuotas, retrieval,
scheduling del enjambre, checkpoints, grafo de dependencias, métricas y evals:

```bash
cd backend
python -m pytest          # 55 tests
make eval                 # arnés de evals (se omite sin claves)
```

---

## Licencia

MIT
