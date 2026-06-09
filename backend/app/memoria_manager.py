import os
import time

MEMORIA_FILENAME = "memoria.md"

def get_memoria_path(project_root: str) -> str:
    return os.path.join(project_root, MEMORIA_FILENAME)

def initialize_memoria_if_needed(project_root: str) -> str:
    """Creates a default memoria.md if it doesn't exist under project_root."""
    memoria_path = get_memoria_path(project_root)
    if os.path.exists(memoria_path):
        return "memoria.md ya existe."

    project_name = os.path.basename(os.path.realpath(project_root))
    creation_date = time.strftime("%Y-%m-%d %H:%M:%S")

    # Simple heuristic to detect stack
    stack = []
    if os.path.exists(os.path.join(project_root, "package.json")):
        stack.append("Node.js/JavaScript")
    if os.path.exists(os.path.join(project_root, "tsconfig.json")):
        stack.append("TypeScript")
    if os.path.exists(os.path.join(project_root, "requirements.txt")) or os.path.exists(os.path.join(project_root, "setup.py")):
        stack.append("Python")
    if os.path.exists(os.path.join(project_root, "Cargo.toml")):
        stack.append("Rust")

    detected_stack = ", ".join(stack) if stack else "No detectado (Stack genérico)"

    content = f"""# 🧠 Memoria del Proyecto: {project_name}

> Este archivo contiene el historial de decisiones técnicas, arquitectura, riesgos y cambios críticos.
> El agente de IA consultará este archivo antes de realizar cualquier cambio sensible o de alto riesgo.

## 📋 Información General
- **Nombre**: {project_name}
- **Creado**: {creation_date}
- **Stack Tecnológico**: {detected_stack}

## 🏗️ Arquitectura y Flujo del Proyecto
- *Describe brevemente los módulos principales y el flujo aquí.*

## 🎯 Archivos Críticos
> Archivos cuya modificación requiere extrema precaución.
- `.env`: Contiene secretos y configuraciones de API.
- `backend/app/main.py`: Entrada del API.
- `backend/app/graph.py`: Flujo del agente de IA.

## 📐 Decisiones Arquitectónicas
| Fecha | Decisión | Razón | Alternativas Consideradas |
|-------|----------|-------|---------------------------|
| {time.strftime("%Y-%m-%d")} | Creación de memoria.md | Adoptar buenas prácticas y bitácora obligatoria | Ninguna |

## 📝 Historial de Cambios
| Fecha | Cambio Realizado | Archivos Modificados | Riesgo | Agente |
|-------|------------------|----------------------|--------|--------|
| {time.strftime("%Y-%m-%d")} | Inicialización de memoria.md | `memoria.md` | Bajo | Swarm-IDE |

## ⚠️ Riesgos Conocidos
- Sin autenticación robusta en localhost.
- Ejecución directa de comandos en terminal.
"""

    try:
        os.makedirs(project_root, exist_ok=True)
        with open(memoria_path, "w", encoding="utf-8") as f:
            f.write(content)
        return "memoria.md inicializado con éxito."
    except Exception as e:
        return f"Error al inicializar memoria.md: {e}"

def is_high_risk_change(description: str, files: list[str]) -> bool:
    """Analyzes if the proposed modification represents a high risk.
    High risk triggers if:
    1. It touches configuration files like package.json, requirements.txt, .env, tsconfig.json, vite.config.ts, tailwind.config.ts, next.config.ts.
    2. Touches 3 or more files.
    3. The description contains keywords associated with refactoring, architecture, removal, deletion, or database changes.
    """
    critical_names = {
        "package.json", "requirements.txt", ".env", "tsconfig.json",
        "next.config.ts", "next.config.js", "tailwind.config.ts",
        "vite.config.ts", "webpack.config.js", "docker-compose.yml",
        "Dockerfile", "main.py", "graph.py", "memoria.md"
    }

    # 1. Critical files check
    for file in files:
        if os.path.basename(file) in critical_names:
            return True

    # 2. Touch count check
    if len(files) >= 3:
        return True

    # 3. Keyword check
    high_risk_keywords = {
        "refactor", "arquitectura", "eliminar", "borrar", "base de datos",
        "database", "migrate", "migracion", "seguridad", "auth", "login",
        "configurar", "setup", "dependency", "dependencia"
    }
    desc_lower = description.lower()
    for kw in high_risk_keywords:
        if kw in desc_lower:
            return True

    return False

def get_last_changelog_lines(project_root: str, n: int = 15) -> str:
    """Return the last N changelog rows from memoria.md as a compact string."""
    memoria_path = get_memoria_path(project_root)
    if not os.path.exists(memoria_path):
        return ""
    try:
        with open(memoria_path, encoding="utf-8") as f:
            content = f.read()
        # Find the changelog table
        table_start = content.find("| Fecha | Cambio Realizado |")
        if table_start == -1:
            return ""
        table_section = content[table_start:]
        rows = [
            line for line in table_section.splitlines()
            if line.startswith("|") and "---" not in line and "Fecha" not in line
        ]
        recent = rows[:n]
        if not recent:
            return ""
        return "| Fecha | Cambio | Archivos | Riesgo | Agente |\n" + "\n".join(recent)
    except Exception:
        return ""


def add_changelog_entry(project_root: str, description: str, files: list[str], risk_level: str, agent_name: str = "Swarm-Agent") -> bool:
    """Appends an entry to the '## 📝 Historial de Cambios' table in memoria.md."""
    memoria_path = get_memoria_path(project_root)
    if not os.path.exists(memoria_path):
        initialize_memoria_if_needed(project_root)

    try:
        with open(memoria_path, encoding="utf-8") as f:
            content = f.read()

        # Format the files list
        files_str = ", ".join([f"`{os.path.basename(f)}`" for f in files])
        if not files_str:
            files_str = "-"

        date_str = time.strftime("%Y-%m-%d %H:%M:%S")
        new_row = f"| {date_str} | {description} | {files_str} | {risk_level} | {agent_name} |\n"

        # Insert row below the table header
        table_header = "| Fecha | Cambio Realizado | Archivos Modificados | Riesgo | Agente |\n|-------|------------------|----------------------|--------|--------|"

        if table_header in content:
            content = content.replace(table_header, table_header + "\n" + new_row)
        else:
            # Fallback append if header is not exact or missing
            content += f"\n\n### Cambio no registrado en tabla ({date_str})\n- **Cambio**: {description}\n- **Archivos**: {files_str}\n- **Riesgo**: {risk_level}\n- **Agente**: {agent_name}\n"

        with open(memoria_path, "w", encoding="utf-8") as f:
            f.write(content)
        return True
    except Exception:
        return False
