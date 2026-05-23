# Swarm IDE

Multi-agent developer IDE powered by OpenRouter with automatic model fallback.

## Inicio rápido

```bash
docker-compose up --build
```

Luego abre: http://localhost:3000

## Uso

1. Escribe tu tarea en la barra superior con toda la precisión posible
2. Pulsa **Ejecutar** (o Enter)
3. El swarm analiza, escribe código, instala dependencias, hace commit — sin preguntar

**Ejemplos de tareas:**
- `Crea una API REST con FastAPI, endpoints CRUD para usuarios, PostgreSQL y tests con pytest`
- `Añade autenticación JWT a la API existente con refresh tokens`
- `Refactoriza el módulo de pagos para usar async/await`
- `Crea un dashboard Next.js con shadcn/ui que consuma esta API`

## Arquitectura

```
backend/          FastAPI + LangGraph + herramientas git/filesystem
frontend/         Next.js 15 + Monaco Editor + streaming SSE
projects/current/ Tu proyecto (montado como volumen Docker)
```

## Fallback de modelos

El swarm cambia de modelo automáticamente si hay errores de créditos/tokens:

1. `anthropic/claude-sonnet-4-5`
2. `anthropic/claude-opus-4-5`
3. `x-ai/grok-3`
4. `google/gemini-2.5-pro-preview`
5. `qwen/qwen3-235b-a22b`
6. `deepseek/deepseek-r1`
7. `anthropic/claude-haiku-4-5`
8. `openai/gpt-4o`
9. `openai/gpt-4o-mini`

Para actualizar la lista edita `backend/app/smart_router.py → MODELS`.

## Atajos de teclado

| Acción | Tecla |
|--------|-------|
| Ejecutar tarea | Enter |
| Guardar archivo | Ctrl+S |
| Formatear código | Ctrl+Shift+F |

## Variables de entorno (.env)

```env
OPENROUTER_API_KEY=sk-or-v1-...   # Requerido
OPENAI_API_KEY=sk-...              # Fallback opcional
ANTHROPIC_API_KEY=sk-ant-...       # Fallback opcional
PROJECT_ROOT=/projects/current     # Dónde trabaja el swarm
```

## Correr localmente (sin Docker)

**Backend:**
```bash
cd backend
pip install -r requirements.txt
PROJECT_ROOT=../projects/current uvicorn app.main:app --reload --port 8000
```

**Frontend:**
```bash
cd frontend
npm install
NEXT_PUBLIC_API_URL=http://localhost:8000 npm run dev
```
