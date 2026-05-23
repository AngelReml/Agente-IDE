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
┌─────────────────────────────────────────────────────────────────────┐
│  Swarm IDE  ⚡  📁 mi-proyecto ▾  │  [escribe tu tarea aquí...]  ⚡▶■ │
├──────────┬───────────────────────────────────┬──────────────────────┤
│          │                                   │                      │
│ ARCHIVOS │         EDITOR DE CÓDIGO          │    PANEL SWARM       │
│          │                                   │    (agentes / git /  │
│          ├───────────────────────────────────┤     modelos)         │
│          │  CONSOLA  │  TERMINAL             │                      │
└──────────┴───────────────────────────────────┴──────────────────────┘
```

---

### Barra superior

| Elemento | Qué hace |
|----------|----------|
| **📁 nombre-proyecto ▾** | Muestra el proyecto activo. Haz clic para cambiar de carpeta. |
| **Caja de texto** | Escribe aquí lo que quieres que haga la IA. Admite varias líneas (`Shift+Enter`). |
| **⚡ / 🔥** | Modo de velocidad. ⚡ = Fast (barato, Groq/GLM). 🔥 = Power (máxima calidad, Claude/GPT). |
| **▶ Ejecutar** | Lanza la IA (`Enter`). |
| **■ Detener** | Para la IA en cualquier momento. |
| **🗑 N ctx** | Mensajes de contexto acumulados. Haz clic para borrar el historial y empezar desde cero. |
| **Icono wifi** | Verde = todo OK. Rojo = algo falla. |

---

### Panel izquierdo — Archivos

Todos los archivos del proyecto activo. Haz clic en uno para abrirlo en el editor.

---

### Centro — Editor de código

Aquí puedes ver y editar cualquier archivo. **Ctrl+S** guarda los cambios.

En el borde del editor, junto a las líneas que la IA ha modificado, aparece un indicador azul. Puedes hacer clic en él para ver el **diff** (qué cambió exactamente) con un resumen generado por IA.

---

### Panel derecho — Swarm

Tres pestañas:

- **⚡ Swarm** — qué agente está activo. Los agentes son especialistas que la IA usa según la tarea (código, diseño, depuración, etc.).
- **🌿 Git** — historial de versiones guardadas automáticamente por la IA.
- **🔗 Modelos** — qué modelo de IA está activo y cuáles hay disponibles. El círculo de color indica el proveedor: 🟠 Anthropic · 🟢 OpenAI · 🔴 Groq · 🔵 GLM · 🟦 Gemini · 🟣 OpenRouter · 🟡 HuggingFace.

---

### Abajo — Consola y Terminal

**Pestaña Consola:** La IA cuenta en tiempo real qué está haciendo.

| Icono | Significado |
|-------|-------------|
| `⟶` | Usando una herramienta (crea archivo, ejecuta comando…) |
| `✓` | Terminó con éxito |
| `⚡` | Cambió a otro modelo de IA (por límite de cuota o error) |
| `✗` | Error encontrado — la IA intentará corregirlo sola |
| `●` | Tarea terminada |
| `💲` | Coste de la operación en tokens y dólares |

**Pestaña Terminal:** Terminal integrada en el navegador. Puedes escribir comandos directamente (Python, npm, git, etc.) sin salir del IDE.

---

### Contador de coste

En la barra inferior de pestañas verás algo como `💲 $0.02 run · $0.08 sesión`. Muestra:
- **run** — coste de la última ejecución
- **sesión** — coste total desde que arrancaste el IDE

---

## Modos de velocidad: ⚡ Fast vs 🔥 Power

El botón ⚡/🔥 junto al campo de tarea elige con qué modelo empieza el agente:

| Modo | Empieza en | Mejor para |
|------|-----------|-----------|
| ⚡ **Fast** | Groq / GLM / DeepSeek | tareas simples, respuesta rápida, coste mínimo |
| 🔥 **Power** | Claude / GPT-4o / Gemini | proyectos complejos, máxima precisión |

Si el modelo elegido falla (cuota agotada, error de red…) la IA salta automáticamente al siguiente de la lista sin que tengas que hacer nada.

---

## Cómo dar una tarea a la IA

### Regla de oro: sé específico

❌ Mal: `"Crea una web"`

✅ Bien: `"Crea una página web de una sola página para mi negocio de repostería. Debe tener un menú con los productos, una sección de contacto con formulario, y un diseño en tonos rosas y blancos. Usa HTML, CSS y JavaScript sin frameworks."`

Cuanta más información des, mejor el resultado.

### Puedes escribir tareas largas

La caja de texto se expande automáticamente. Usa `Shift+Enter` para añadir saltos de línea. `Enter` ejecuta la tarea.

### Ejemplos

- `"Crea una API en Python con FastAPI que gestione una lista de clientes: crear, editar, borrar y listar. Guarda los datos en un archivo JSON."`
- `"Crea un script en Python que lea un archivo CSV con ventas mensuales y genere un resumen con el total, la media y el mes con más ventas."`
- `"Crea una página HTML con una calculadora de presupuestos para eventos. Campos: número de invitados, tipo de evento, y extras opcionales."`
- `"Revisa todo el código del proyecto, identifica errores y corrígelos sin cambiar la funcionalidad existente."`
- `"Añade tests unitarios con pytest a todos los módulos de backend que aún no los tengan."`

---

## Cambiar de proyecto

Por defecto el IDE trabaja en la carpeta `swarm-ide\projects\current\`.

Para trabajar en **otro proyecto tuyo**:

1. Haz clic en el nombre del proyecto en la barra superior (📁).
2. Escribe o pega la ruta completa de la carpeta (ejemplo: `C:\Users\angel\Desktop\mi-app`).
3. Pulsa **Cambiar**. La IA empieza a trabajar en esa carpeta.

El cambio se guarda en el archivo `.env`. No hace falta reiniciar.

> **Nota:** al cambiar de proyecto el historial de conversación se mantiene. Si quieres que el agente empiece fresco, pulsa **🗑 N ctx** en la barra superior para borrar el contexto.

---

## Restaurar una versión anterior de un archivo (Timeline)

El IDE guarda automáticamente copias de seguridad cada vez que la IA modifica un archivo.

Para restaurar:

1. Abre el archivo en el editor.
2. En la parte superior del editor verás un enlace **"N versiones"** o un icono de reloj.
3. Haz clic, elige la versión que quieres recuperar y pulsa **Restaurar**.

---

## Atajos de teclado

| Acción | Tecla |
|--------|-------|
| Ejecutar tarea | `Enter` |
| Nueva línea en el input | `Shift+Enter` o `Alt+Enter` |
| Guardar archivo | `Ctrl+S` |
| Formatear código | `Ctrl+Shift+F` |

---

## ¿Dónde se guardan los archivos que crea la IA?

En la carpeta del proyecto activo (visible en la barra superior). Por defecto:

```
C:\Users\TU_USUARIO\Desktop\swarm-ide\projects\current\
```

Puedes abrirla con el explorador de archivos normal y ver, copiar o mover todo lo que la IA haya creado.

---

## Solución de problemas

### "La página no carga" / pantalla en blanco
Las dos ventanas negras deben estar abiertas. Si las cerraste, vuelve a ejecutar `INICIAR.bat`.

### El icono wifi aparece rojo
Misma solución: ejecuta `INICIAR.bat`. El motor (backend) no está corriendo.

### "La IA se paró a mitad de la tarea"
Pulsa **▶ Ejecutar** de nuevo con la misma tarea. La IA revisará lo que ya existe y continuará desde donde lo dejó.

### "La IA cambia de modelo constantemente"
Significa que los modelos de mayor prioridad tienen la cuota agotada. Tienes dos opciones:
- Esperar a que se renueven los límites (normalmente al día siguiente).
- Añadir créditos en la plataforma correspondiente (Anthropic, Google AI Studio, etc.).
- Usar el modo ⚡ Fast, que empieza en Groq (que tiene capa gratuita generosa).

### "La tarea me costó mucho dinero"
Usa el modo ⚡ Fast para tareas simples. Reserva 🔥 Power para proyectos complejos. El coste se muestra en la barra inferior.

### La IA escribe código vacío o loops sin avanzar
Pulsa **■ Detener**, borra el contexto (🗑 ctx) y vuelve a lanzar la tarea con una descripción más precisa de lo que quieres. A veces ayuda dividir la tarea en pasos más pequeños.

### Quiero empezar de cero / borrar lo que creó
Borra el contenido de la carpeta del proyecto. Los archivos del IDE no se tocan.

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
