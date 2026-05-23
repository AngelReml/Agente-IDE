# Swarm IDE — Manual de Usuario

> Para personas sin conocimientos técnicos. Sin jerga. Sin rodeos.

---

## ¿Qué es Swarm IDE?

Una aplicación que tienes instalada en tu ordenador. Abres el navegador, escribes lo que quieres construir en lenguaje normal, y la aplicación lo construye sola usando inteligencia artificial.

No necesitas saber programar. No necesitas escribir código. Solo describes lo que necesitas.

---

## Requisitos (instalar una sola vez)

Tres programas gratuitos. Si ya los tienes, no hace falta instalarlos de nuevo.

| Programa | Dónde descargarlo | Notas |
|----------|-------------------|-------|
| **Python 3.11+** | python.org/downloads | Marca "Add Python to PATH" durante la instalación |
| **Node.js 18+** | nodejs.org | Instalación estándar, sin opciones especiales |
| **Git** | git-scm.com/download/win | Instalación estándar |

---

## Instalación (solo la primera vez)

1. Abre la carpeta `swarm-ide` en el escritorio.
2. Haz doble clic en **`INSTALAR.bat`**.
3. Espera a que termine (2–5 minutos, descarga dependencias).
4. Cuando aparezca "Instalación completada", cierra la ventana.

Listo. No hay que repetir esto nunca más.

---

## Cómo arrancar la aplicación

Haz doble clic en **`INICIAR.bat`**.

Se abren dos ventanas negras (una para el motor, otra para la interfaz) y el navegador se abre solo en `http://localhost:3000`.

**Esas dos ventanas negras deben quedarse abiertas mientras usas el IDE.** No las cierres.

---

## La pantalla principal — qué es cada cosa

```
┌────────────────────────────────────────────────────────┐
│  ⚡ Swarm IDE  │  [escribe tu tarea aquí...]  │ ▶ Ejecutar │
├──────────┬──────────────────────────────────┬───────────┤
│          │                                  │           │
│ ARCHIVOS │        EDITOR DE CÓDIGO          │   PANEL   │
│          │                                  │   SWARM   │
│          ├──────────────────────────────────┤           │
│          │        CONSOLA (OUTPUT)          │           │
└──────────┴──────────────────────────────────┴───────────┘
```

### Barra superior
- **Caja de texto** — escribe aquí lo que quieres que haga la IA.
- **▶ Ejecutar** — lanza la IA.
- **■ Detener** — para la IA en cualquier momento.
- **Icono wifi** — verde = todo OK. Rojo = algo falla (comprueba que las dos ventanas negras siguen abiertas).

### Panel izquierdo — Archivos
Todos los archivos que la IA ha creado. Haz clic en uno para abrirlo en el editor.

### Centro — Editor de código
Aquí puedes ver y editar cualquier archivo. **Ctrl+S** guarda cambios manuales.

### Panel derecho — Swarm
- **⚡ Swarm** — qué tipo de agente está activo en este momento. Los agentes son como "expertos" especializados que la IA utiliza para diferentes tareas (por ejemplo, un experto en código, un experto en diseño, etc.).
- **🌿 Git** — historial de versiones guardadas automáticamente.
- **🔗 Modelos** — qué modelo de IA está activo y cuáles hay disponibles.
- El **círculo de color** indica el proveedor: naranja = Anthropic (Claude), verde = OpenAI (GPT), rojo = Groq, violeta = OpenRouter.

### Abajo — Consola
La IA cuenta en tiempo real qué está haciendo. Aquí verás mensajes de los agentes, las herramientas que utilizan (como crear archivos, ejecutar comandos, etc.) y cualquier error que pueda surgir. Iconos:
- `⟶` Usando una herramienta (crea archivo, ejecuta comando…)
- `✓` Terminó con éxito
- `⚡` Cambió a otro modelo de IA (por límite de cuota)
- `✗` Error encontrado — la IA intentará corregirlo sola
- `●` Tarea terminada

---

## Cómo dar una tarea a la IA

### Regla de oro: sé específico

❌ Mal: `"Crea una web"`

✅ Bien: `"Crea una página web de una sola página para mi negocio de repostería. Debe tener un menú con los productos, una sección de contacto con formulario, y un diseño en tonos rosas y blancos. Usa HTML, CSS y JavaScript sin frameworks."`

Cuanta más información des, mejor el resultado.

### Ejemplos

- `"Crea una API en Python con FastAPI que gestione una lista de clientes: crear, editar, borrar y listar. Guarda los datos en un archivo JSON."`
- `"Crea un script en Python que lea un archivo CSV con ventas mensuales y genere un resumen con el total, la media y el mes con más ventas."`
- `"Crea una página HTML con una calculadora de presupuestos para eventos. Campos: número de invitados, tipo de evento, y extras opcionales."`
- `"Escribe un programa en Python que monitorice una carpeta y avise cuando aparezca un archivo nuevo."`

---

## ¿Dónde se guardan los archivos que crea la IA?

En esta carpeta de tu ordenador:

```
C:\Users\angel\Desktop\swarm-ide\projects\current\
```

Puedes abrirla con el explorador de archivos normal y ver, copiar o mover todo lo que la IA haya creado.

Si quieres que trabaje en otra carpeta (por ejemplo un proyecto tuyo existente), cambia la línea `PROJECT_ROOT` en el archivo `.env` que hay en la carpeta `swarm-ide`.

---

## Solución de problemas

### "La página no carga" / pantalla en blanco
Las dos ventanas negras deben estar abiertas. Si las cerraste, vuelve a ejecutar `INICIAR.bat`.

### El icono wifi aparece rojo
Misma solución: ejecuta `INICIAR.bat`. El motor (backend) no está corriendo.

### "La IA se paró a mitad de la tarea"
Pulsa **▶ Ejecutar** de nuevo con la misma tarea. La IA revisará lo que ya existe y continuará.

### Quiero empezar de cero / borrar lo que creó
Borra el contenido de `swarm-ide\projects\current\`. Los archivos del IDE no se tocan.

---

## Cómo parar la aplicación

Haz doble clic en **`PARAR.bat`**, o simplemente cierra las dos ventanas negras.

---

## Resumen de scripts

| Script | Qué hace | Cuándo usarlo |
|--------|----------|---------------|
| `INSTALAR.bat` | Instala todo lo necesario | Solo la primera vez |
| `INICIAR.bat` | Arranca el IDE | Cada vez que quieras usarlo |
| `PARAR.bat` | Para el IDE | Cuando termines |
