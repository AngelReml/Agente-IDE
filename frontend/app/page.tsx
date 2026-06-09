'use client'

import { useState, useCallback, useRef, useEffect } from 'react'
import { Play, Square, WifiOff, Wifi, ChevronLeft, ChevronRight, PanelBottomOpen, PanelBottomClose, X, Trash2, TerminalSquare, FolderOpen } from 'lucide-react'
import { FileExplorer }   from '@/components/FileExplorer'
import { MonacoEditor }   from '@/components/MonacoEditor'
import { AgentPanel }     from '@/components/AgentPanel'
import { OutputConsole }  from '@/components/OutputConsole'
import { ApprovalModal }  from '@/components/ApprovalModal'
import { Terminal }       from '@/components/Terminal'
import { OutputEvent, Provider, FileCard } from '@/types'
import { fetchFileContent, saveFileContent, runSwarmTask, checkHealth, selectModel, fetchChatContext, clearChatContext, fetchProject, switchProject, fetchRecentProjects, fetchRoutingMode, setRoutingMode, fetchCost, fetchGitDiff, fetchDiffSummary } from '@/lib/api'
import { cn } from '@/lib/utils'

const MAX_EVENTS = 4000

// ── Konami Code sequence ─────────────────────────────────────────────────────
const KONAMI = ['ArrowUp','ArrowUp','ArrowDown','ArrowDown','ArrowLeft','ArrowRight','ArrowLeft','ArrowRight','b','a']

// ── River of Cards — FFIX parchment style ────────────────────────────────────
function RiverCard({ card, onOpen }: { card: FileCard; onOpen: (path: string) => void }) {
  const risk      = card.summary?.nivel_riesgo
  const isHighRisk = risk === 'alto'
  const isMedRisk  = risk === 'medio'

  return (
    <div
      onClick={() => onOpen(card.path)}
      className="file-card flex-shrink-0 w-48 rounded cursor-pointer transition-all group"
      style={{
        background:  'linear-gradient(145deg, #0e1530 0%, #0a0f24 100%)',
        border:      `1px solid ${isHighRisk ? 'rgba(201,64,64,0.30)' : isMedRisk ? 'rgba(201,160,48,0.30)' : 'rgba(160,120,40,0.22)'}`,
        boxShadow:   isHighRisk ? '0 0 14px rgba(201,64,64,0.08)' : 'none',
      }}
      onMouseEnter={e => (e.currentTarget.style.borderColor = isHighRisk ? 'rgba(201,64,64,0.5)' : isMedRisk ? 'rgba(201,160,48,0.5)' : 'rgba(201,160,48,0.35)')}
      onMouseLeave={e => (e.currentTarget.style.borderColor = isHighRisk ? 'rgba(201,64,64,0.30)' : isMedRisk ? 'rgba(201,160,48,0.30)' : 'rgba(160,120,40,0.22)')}
    >
      <div className="p-2.5">
        <div className="flex items-center gap-1.5 mb-1.5">
          <div className={cn('w-1.5 h-1.5 rounded-full flex-shrink-0',
            card.loadingSummary ? 'animate-pulse' : '')}
            style={{
              background: card.loadingSummary ? '#c9a030' : '#4abcaa',
              boxShadow:  !card.loadingSummary ? '0 0 4px rgba(74,188,170,0.6)' : undefined,
            }} />
          <span className="text-[11px] font-mono truncate" style={{ color: '#c4a870' }} title={card.path}>
            {card.filename}
          </span>
        </div>

        {card.loadingSummary ? (
          <div className="text-[10px] animate-pulse font-mono" style={{ color: 'rgba(140,100,40,0.5)' }}>
            Leyendo el pergamino…
          </div>
        ) : card.summary ? (
          <p className="text-[10px] leading-relaxed line-clamp-2" style={{ color: 'rgba(140,100,40,0.8)' }}>
            {card.summary.resumen_humano}
          </p>
        ) : (
          <p className="text-[10px]" style={{ color: 'rgba(120,85,35,0.6)' }}>Pergamino alterado</p>
        )}

        <div className="flex items-center gap-2 mt-2 pt-1.5"
          style={{ borderTop: '1px solid rgba(160,120,40,0.15)' }}>
          {card.summary?.stats ? (
            <>
              <span className="text-[9px] font-mono" style={{ color: '#5dbc6e' }}>+{card.summary.stats.lines_added}</span>
              <span className="text-[9px] font-mono" style={{ color: '#c94040' }}>-{card.summary.stats.lines_removed}</span>
            </>
          ) : null}
          <span className="text-[9px] font-mono ml-auto" style={{ color: 'rgba(120,85,35,0.5)' }}>
            {new Date(card.timestamp).toLocaleTimeString('es', { hour: '2-digit', minute: '2-digit', second: '2-digit' })}
          </span>
        </div>
      </div>

      {risk && (
        <div className="px-2 py-0.5 text-[8px] font-cinzel uppercase tracking-widest"
          style={{
            borderTop: `1px solid ${isHighRisk ? 'rgba(201,64,64,0.18)' : isMedRisk ? 'rgba(201,160,48,0.18)' : 'rgba(160,120,40,0.15)'}`,
            color:     isHighRisk ? 'rgba(201,64,64,0.75)' : isMedRisk ? 'rgba(201,160,48,0.75)' : 'rgba(74,188,170,0.6)',
            background: isHighRisk ? 'rgba(201,64,64,0.04)' : isMedRisk ? 'rgba(201,160,48,0.04)' : 'transparent',
          }}>
          {risk} riesgo
        </div>
      )}
    </div>
  )
}

// ── Main Page ────────────────────────────────────────────────────────────────
export default function SwarmIDE() {
  // Editor state
  const [activeFile, setActiveFile]   = useState<string | null>(null)
  const [fileContent, setFileContent] = useState('')
  const [isDirty, setIsDirty]         = useState(false)
  const [saving, setSaving]           = useState(false)
  const [fileError, setFileError]     = useState<string | null>(null)

  // Task & run state
  const [task, setTask]               = useState('')
  const [isRunning, setIsRunning]     = useState(false)
  const [activeModel, setActiveModel] = useState<string | null>(null)
  const [activeProvider, setActiveProvider] = useState<Provider>(null)
  const [activeTool, setActiveTool]   = useState<string | null>(null)
  const abortRef = useRef<AbortController | null>(null)
  const sessionIdRef = useRef(`sess-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`)

  // Populate a river card's summary from the real git diff (B4 — previously dead path).
  const loadCardSummary = useCallback(async (filePath: string) => {
    try {
      const diff = await fetchGitDiff(filePath)
      const summary = diff ? await fetchDiffSummary(filePath, diff) : null
      if (summary) {
        setFileCards((prev) => prev.map((c) => c.path === filePath ? { ...c, summary, loadingSummary: false } : c))
      }
    } catch {
      /* leave card without summary */
    }
  }, [])

  // Output
  const [events, setEvents]           = useState<OutputEvent[]>([])
  const [pendingApproval, setPendingApproval] = useState<string | null>(null)

  // River of Cards
  const [fileCards, setFileCards]     = useState<FileCard[]>([])

  // Spell cast shimmer
  const [castShimmer, setCastShimmer] = useState(false)

  // Stale-closure-safe active file ref
  const activeFileRef = useRef<string | null>(null)
  useEffect(() => { activeFileRef.current = activeFile }, [activeFile])

  // Panel visibility
  const [showFileTree, setShowFileTree]     = useState(true)
  const [showAgentPanel, setShowAgentPanel] = useState(true)
  const [showOutput, setShowOutput]         = useState(true)

  // Refresh triggers
  const [fileTreeRefresh, setFileTreeRefresh] = useState(0)
  const [agentRefresh, setAgentRefresh]       = useState(0)

  // Backend health
  const [backendOnline, setBackendOnline] = useState<boolean | null>(null)

  // Session context message count
  const [contextMsgCount, setContextMsgCount] = useState(0)

  // Cost counter
  const [runCost, setRunCost]         = useState(0)
  const [sessionCost, setSessionCost] = useState(0)

  // Routing mode
  const [routingMode, setRoutingModeState] = useState<'fast' | 'power'>('fast')

  // Swarm mode — parallel multi-agent orchestration (/run/swarm)
  const [swarmMode, setSwarmMode] = useState(false)

  // Bottom panel
  const [bottomPanel, setBottomPanel] = useState<'console' | 'terminal'>('console')

  // Project switcher
  const [projectPath, setProjectPath]       = useState('')
  const [showProjectModal, setShowProjectModal] = useState(false)
  const [projectInput, setProjectInput]     = useState('')
  const [projectError, setProjectError]     = useState('')
  const [recentProjects, setRecentProjects] = useState<string[]>([])

  // ── Easter Egg: Konami Code → Moogle ──────────────────────────────────────
  const [showMoogle, setShowMoogle] = useState(false)
  const konamiRef = useRef<string[]>([])
  useEffect(() => {
    const handle = (e: KeyboardEvent) => {
      konamiRef.current = [...konamiRef.current, e.key].slice(-10)
      if (konamiRef.current.join(',') === KONAMI.join(',')) {
        setShowMoogle(true)
        setTimeout(() => setShowMoogle(false), 5000)
        konamiRef.current = []
      }
    }
    window.addEventListener('keydown', handle)
    return () => window.removeEventListener('keydown', handle)
  }, [])

  // ── Health check ──────────────────────────────────────────────────────────
  useEffect(() => {
    const check = async () => {
      const result = await checkHealth()
      setBackendOnline(result.online)
      if (result.online && result.provider) setActiveProvider(result.provider as Provider)
      if (result.online && result.model)    setActiveModel(result.model)
    }
    check()
    const id = setInterval(check, 10_000)
    return () => clearInterval(id)
  }, [])

  useEffect(() => {
    fetchChatContext().then((r) => setContextMsgCount(r.messages))
  }, [agentRefresh])

  useEffect(() => {
    fetchProject().then((r) => { setProjectPath(r.path); setProjectInput(r.path) }).catch(() => {})
    fetchRecentProjects().then(setRecentProjects).catch(() => {})
    fetchRoutingMode(sessionIdRef.current).then(setRoutingModeState).catch(() => {})
  }, [])

  const handleToggleMode = useCallback(async () => {
    const next: 'fast' | 'power' = routingMode === 'fast' ? 'power' : 'fast'
    setRoutingModeState(next)
    await setRoutingMode(next, sessionIdRef.current).catch(() => {})
  }, [routingMode])

  useEffect(() => {
    if (!fileError) return
    const id = setTimeout(() => setFileError(null), 4000)
    return () => clearTimeout(id)
  }, [fileError])

  useEffect(() => {
    if (!castShimmer) return
    const id = setTimeout(() => setCastShimmer(false), 900)
    return () => clearTimeout(id)
  }, [castShimmer])

  // ── File operations ───────────────────────────────────────────────────────
  const openFile = useCallback(async (path: string) => {
    try {
      const content = await fetchFileContent(path)
      setActiveFile(path)
      setFileContent(content)
      setIsDirty(false)
      setFileError(null)
    } catch {
      setFileError(`No se pudo abrir el pergamino: ${path}`)
    }
  }, [])

  const handleContentChange = useCallback((value: string) => {
    setFileContent(value)
    setIsDirty(true)
  }, [])

  const handleSave = useCallback(async () => {
    if (!activeFile || !isDirty) return
    setSaving(true)
    try {
      await saveFileContent(activeFile, fileContent)
      setIsDirty(false)
      setFileError(null)
    } catch (e: any) {
      setFileError(`Error al inscribir: ${e?.message ?? 'desconocido'}`)
    } finally {
      setSaving(false)
    }
  }, [activeFile, fileContent, isDirty])

  // ── Task execution ────────────────────────────────────────────────────────
  const handleRun = useCallback(async (overrideTask?: string) => {
    const currentTask = overrideTask ?? task
    if (!currentTask.trim() || isRunning) return

    setIsRunning(true)
    setActiveTool(null)
    setEvents([])
    setFileCards([])
    setRunCost(0)
    setCastShimmer(true)
    abortRef.current = new AbortController()

    try {
      await runSwarmTask(
        currentTask,
        (event) => {
          setEvents((prev) => {
            const next = [...prev, event]
            return next.length > MAX_EVENTS ? next.slice(next.length - MAX_EVENTS) : next
          })

          if (event.type === 'tool_start' && event.tool) {
            setActiveTool(event.tool)
            if (event.tool === 'write_file') {
              // Prefer the structured `path` field; regex is just a fallback.
              const filePath  = event.path ?? (event.content.match(/^(.+?)\s*\(/)?.[1]?.trim() ?? event.content)
              const filename  = filePath.split(/[/\\]/).pop() ?? filePath
              const card: FileCard = { path: filePath, filename, timestamp: Date.now(), loadingSummary: true }
              setFileCards((prev) => {
                const without = prev.filter((c) => c.path !== filePath)
                return [...without, card]
              })
            }
          }

          if (event.type === 'tool_end' && (event.needs_confirmation || event.content?.includes('CONFIRMACION REQUERIDA'))) {
            setPendingApproval(event.content)
            abortRef.current?.abort()
          }

          if (event.type === 'tool_end' && event.tool === 'write_file') {
            const filePath = event.path ?? (event.content.match(/^✅\s+(.+?)\s*\(/)?.[1]?.trim() ?? null)
            if (filePath) {
              setFileCards((prev) => prev.map((c) => c.path === filePath ? { ...c, loadingSummary: false } : c))
              loadCardSummary(filePath)
            } else {
              setFileCards((prev) => prev.map((c) => ({ ...c, loadingSummary: false })))
            }
          }

          if (event.type === 'tool_end' || event.type === 'done') setActiveTool(null)

          if (event.type === 'model_switch') {
            if (event.new_model) setActiveModel(event.new_model)
            if (event.provider)  setActiveProvider(event.provider as Provider)
          }
          if (event.type === 'info' && event.model) {
            setActiveModel(event.model)
            if (event.provider) setActiveProvider(event.provider as Provider)
          }
          if (event.type === 'context') {
            fetchChatContext().then((r) => setContextMsgCount(r.messages))
          }
          if (event.type === 'cost' && event.cost_usd !== undefined) {
            setRunCost(event.cost_usd)
          }
          if (event.type === 'done') {
            setFileTreeRefresh((n) => n + 1)
            setAgentRefresh((n) => n + 1)
            // B3: read the real cumulative session cost from the backend.
            fetchCost(sessionIdRef.current).then((c) => setSessionCost(c.session.cost_usd)).catch(() => {})
            fetchChatContext().then((r) => setContextMsgCount(r.messages))
            const cur = activeFileRef.current
            if (cur) {
              fetchFileContent(cur)
                .then((c) => { setFileContent(c); setIsDirty(false) })
                .catch(() => {})
            }
          }
        },
        abortRef.current.signal,
        sessionIdRef.current,
        swarmMode ? '/run/swarm' : '/run',
      )
    } catch (e: any) {
      if (e?.name !== 'AbortError') {
        setEvents((prev) => [
          ...prev,
          { id: `err-${Date.now()}`, type: 'error', content: String(e?.message ?? e), timestamp: Date.now() },
        ])
      }
    } finally {
      setIsRunning(false)
      setActiveTool(null)
    }
  }, [task, isRunning, swarmMode, loadCardSummary])

  const handleApprove = useCallback(() => {
    if (!pendingApproval) return
    const suffix = ' (Confirmado: procede con overwrite_external=True o confirmed=True)'
    const nextTask = task.endsWith(suffix) ? task : task + suffix
    setTask(nextTask)
    setPendingApproval(null)
    setTimeout(() => handleRun(nextTask), 100)
  }, [pendingApproval, task, handleRun])

  const handleModelSelect = useCallback(async (modelId: string) => {
    try {
      await selectModel(modelId, sessionIdRef.current)
      setActiveModel(modelId)
      setAgentRefresh((n) => n + 1)
      const health = await checkHealth()
      if (health.provider) setActiveProvider(health.provider as Provider)
    } catch {
      setFileError('No se pudo invocar el Eidolón')
    }
  }, [])

  const handleStop = useCallback(() => {
    abortRef.current?.abort()
    setIsRunning(false)
    setActiveTool(null)
    setFileCards((prev) => prev.map((c) => ({ ...c, loadingSummary: false })))
    setEvents((prev) => [
      ...prev,
      { id: `stop-${Date.now()}`, type: 'info', content: '⏹ El héroe ha huido del combate', timestamp: Date.now() },
    ])
  }, [])

  const handleClearContext = useCallback(async () => {
    await clearChatContext()
    setContextMsgCount(0)
    setEvents((prev) => [
      ...prev,
      { id: `ctx-${Date.now()}`, type: 'info', content: '🐾 Kupo! Memoria borrada — el próximo hechizo comienza desde cero', timestamp: Date.now() },
    ])
  }, [])

  const handleSwitchProject = useCallback(async (path: string) => {
    setProjectError('')
    try {
      const res = await switchProject(path)
      setProjectPath(res.path)
      setProjectInput(res.path)
      setShowProjectModal(false)
      setFileTreeRefresh((n) => n + 1)
      setFileError('Mundo cambiado — invocar un Chocobo para aplicar los cambios')
    } catch (e: any) {
      setProjectError(e?.message ?? 'Error al viajar al mundo')
    }
  }, [])

  const handleFileRestored = useCallback(() => {
    const cur = activeFileRef.current
    if (cur) {
      fetchFileContent(cur)
        .then((c) => { setFileContent(c); setIsDirty(false) })
        .catch(() => {})
    }
    setFileTreeRefresh((n) => n + 1)
    setAgentRefresh((n) => n + 1)
  }, [])

  const taskRef = useRef<HTMLTextAreaElement>(null)
  const autoResize = useCallback(() => {
    const el = taskRef.current
    if (!el) return
    el.style.height = 'auto'
    el.style.height = Math.min(el.scrollHeight, 160) + 'px'
  }, [])

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey && !e.altKey) {
      e.preventDefault()
      if (isRunning) handleStop()
      else { setCastShimmer(true); handleRun() }
    }
  }

  // ── Render ────────────────────────────────────────────────────────────────
  return (
    <div className="flex flex-col h-screen overflow-hidden" style={{ background: '#080c1a' }}>

      {/* ══ Moogle Easter Egg Overlay (Konami Code) ══════════════════════════ */}
      {showMoogle && (
        <div className="fixed inset-0 z-[200] flex items-center justify-center pointer-events-none"
          style={{ background: 'rgba(8,12,26,0.92)', backdropFilter: 'blur(6px)' }}>
          <div className="text-center moogle-entrance">
            <div className="text-[96px] moogle-float select-none" style={{ lineHeight: 1 }}>
              🐾
            </div>
            <div className="mt-4 text-[40px] font-cinzel tracking-widest" style={{ color: '#c9a030' }}>
              Kupo!
            </div>
            <div className="mt-2 text-[13px] font-crimson italic" style={{ color: 'rgba(201,160,48,0.65)' }}>
              ✦ The Moogles watch over thy quest ✦
            </div>
            <div className="mt-1 text-[11px] font-mono" style={{ color: 'rgba(140,100,40,0.5)' }}>
              — Mognet Secret —
            </div>
          </div>
        </div>
      )}

      {/* ══ Header — The Oracle Scroll ════════════════════════════════════════ */}
      <header className="flex items-start gap-2 px-3 py-2 flex-shrink-0 min-h-[48px]"
        style={{
          borderBottom: '1px solid rgba(160,120,40,0.22)',
          background:   'linear-gradient(to right, #0c1128, #0e1230)',
          boxShadow:    'inset 0 -1px 0 rgba(201,160,48,0.04)',
        }}>

        {/* Logo */}
        <div className="flex items-center gap-2 mr-2 flex-shrink-0 mt-0.5">
          <div className="w-6 h-6 rounded flex items-center justify-center text-[12px]"
            style={{ background: 'rgba(201,160,48,0.10)', border: '1px solid rgba(201,160,48,0.22)' }}>
            ✦
          </div>
          <span className="text-[12px] font-cinzel text-parch-2 hidden sm:block tracking-wider"
            style={{ color: 'rgba(201,160,48,0.75)' }}>
            Swarm IDE
          </span>
        </div>

        {/* Spell Input */}
        <div className="flex-1 min-w-0 relative">
          <div className={cn(
            'flex items-center gap-2 rounded border transition-all overflow-hidden',
          )} style={{
            borderColor: isRunning ? 'rgba(201,160,48,0.30)' : 'rgba(160,120,40,0.22)',
            background:  isRunning ? 'rgba(201,160,48,0.04)' : 'rgba(12,17,40,0.8)',
            boxShadow:   isRunning ? '0 0 12px rgba(201,160,48,0.06)' : 'inset 0 1px 0 rgba(0,0,0,0.3)',
          }}>
            {/* Cast shimmer */}
            {castShimmer && <div className="crystal-shimmer" />}

            <textarea
              ref={taskRef}
              value={task}
              rows={1}
              onChange={(e) => { setTask(e.target.value); autoResize() }}
              onKeyDown={handleKeyDown}
              placeholder="Describe tu hazaña…  (⏎ conjurar · Shift+⏎ nueva línea)"
              disabled={isRunning}
              className={cn(
                'flex-1 bg-transparent px-3 py-1.5 text-[13px] transition-colors min-w-0',
                'focus:outline-none resize-none leading-relaxed font-crimson',
              )}
              style={{
                color:       isRunning ? 'rgba(180,140,60,0.55)' : '#e0c878',
                caretColor:  '#c9a030',
                maxHeight:   '160px',
                overflowY:   'auto',
                cursor:      isRunning ? 'not-allowed' : undefined,
              }}
            />

            {/* Routing mode toggle — Ranger / Summoner */}
            <button
              onClick={handleToggleMode}
              disabled={isRunning}
              title={routingMode === 'fast'
                ? 'Modo Ranger: Groq/GLM (rápido y económico). Click → Summoner'
                : 'Modo Summoner: Anthropic/OpenAI (poderoso). Click → Ranger'}
              className="flex-shrink-0 self-start mt-0.5 px-2 py-1.5 rounded text-[11px] font-cinzel font-semibold transition-all disabled:opacity-40 tracking-wide"
              style={routingMode === 'fast'
                ? { background: 'rgba(74,188,170,0.10)', color: '#4abcaa', border: '1px solid rgba(74,188,170,0.22)' }
                : { background: 'rgba(201,149,74,0.10)', color: '#e0954a', border: '1px solid rgba(201,149,74,0.25)' }}
            >
              {routingMode === 'fast' ? '⚡' : '🔥'}
            </button>

            {/* Swarm toggle — single agent vs parallel multi-agent */}
            <button
              onClick={() => setSwarmMode((s) => !s)}
              disabled={isRunning}
              title={swarmMode
                ? 'Modo Enjambre: planner + agentes en paralelo. Click → Agente único'
                : 'Modo Agente único. Click → Enjambre (multi-agente paralelo)'}
              className="flex-shrink-0 self-start mt-0.5 px-2 py-1.5 rounded text-[11px] font-cinzel font-semibold transition-all disabled:opacity-40 tracking-wide"
              style={swarmMode
                ? { background: 'rgba(155,122,205,0.12)', color: '#b89bdd', border: '1px solid rgba(155,122,205,0.30)' }
                : { background: 'rgba(120,90,35,0.06)', color: 'rgba(160,120,40,0.55)', border: '1px solid rgba(160,120,40,0.20)' }}
            >
              {swarmMode ? '🐝' : '🜂'}
            </button>

            {/* Cast / Flee */}
            {!isRunning ? (
              <button
                onClick={() => { setCastShimmer(true); handleRun() }}
                disabled={!task.trim()}
                className="flex items-center gap-1.5 px-3 py-1.5 mr-1 mt-0.5 rounded text-[12px] font-cinzel font-medium transition-all flex-shrink-0 self-start disabled:opacity-30 disabled:cursor-not-allowed tracking-wide"
                style={{ background: 'rgba(201,160,48,0.12)', color: '#c9a030', border: '1px solid rgba(201,160,48,0.25)' }}
                onMouseEnter={e => {
                  if (task.trim()) {
                    e.currentTarget.style.background = 'rgba(201,160,48,0.20)'
                    e.currentTarget.style.boxShadow  = '0 0 12px rgba(201,160,48,0.15)'
                  }
                }}
                onMouseLeave={e => {
                  e.currentTarget.style.background = 'rgba(201,160,48,0.12)'
                  e.currentTarget.style.boxShadow  = ''
                }}
              >
                <Play size={12} />
                <span className="hidden sm:inline">Conjurar</span>
              </button>
            ) : (
              <button
                onClick={handleStop}
                className="flex items-center gap-1.5 px-3 py-1.5 mr-1 mt-0.5 rounded text-[12px] font-cinzel font-medium flex-shrink-0 self-start transition-all tracking-wide"
                style={{ background: 'rgba(201,64,64,0.12)', color: '#c94040', border: '1px solid rgba(201,64,64,0.25)' }}
              >
                <Square size={12} />
                <span className="hidden sm:inline">Huir</span>
              </button>
            )}
          </div>
        </div>

        {/* Right controls */}
        <div className="flex items-center gap-1 ml-1 flex-shrink-0 mt-0.5">
          {/* Context clear */}
          {contextMsgCount > 0 && (
            <button
              onClick={handleClearContext}
              disabled={isRunning}
              title={`Memoria de sesión: ${contextMsgCount} mensajes. Click para olvidar — Kupo!`}
              className="flex items-center gap-1 px-2 py-1 rounded text-[10px] font-mono transition-all hover:opacity-80 disabled:opacity-40"
              style={{ background: 'rgba(201,160,48,0.06)', border: '1px solid rgba(201,160,48,0.18)', color: 'rgba(201,160,48,0.65)' }}
            >
              🐾
              <span className="hidden md:inline">{contextMsgCount}</span>
            </button>
          )}

          {/* Backend status */}
          <div className={cn('flex items-center gap-1 px-2 py-1 rounded text-[11px] font-mono')}>
            {backendOnline
              ? <Wifi size={11} style={{ color: '#5dbc6e' }} />
              : <WifiOff size={11} style={{ color: '#c94040' }} />}
            <span className="hidden md:inline text-[10px]"
              style={{ color: backendOnline === null ? 'rgba(140,100,40,0.4)' : backendOnline ? 'rgba(93,188,110,0.7)' : 'rgba(201,64,64,0.7)' }}>
              {backendOnline === null ? '…' : backendOnline ? 'online' : 'offline'}
            </span>
          </div>

          <div className="w-px h-4 mx-1" style={{ background: 'rgba(160,120,40,0.20)' }} />

          <button
            onClick={() => setShowFileTree(!showFileTree)}
            className="p-1.5 rounded transition-colors"
            style={{ color: showFileTree ? 'rgba(201,160,48,0.7)' : 'rgba(120,90,35,0.5)', background: showFileTree ? 'rgba(201,160,48,0.06)' : undefined }}
            title="Tomes"
          >
            {showFileTree ? <ChevronLeft size={13} /> : <ChevronRight size={13} />}
          </button>
          <button
            onClick={() => setShowOutput(!showOutput)}
            className="p-1.5 rounded transition-colors"
            style={{ color: showOutput ? 'rgba(201,160,48,0.7)' : 'rgba(120,90,35,0.5)', background: showOutput ? 'rgba(201,160,48,0.06)' : undefined }}
            title="Diario de batalla"
          >
            {showOutput ? <PanelBottomClose size={13} /> : <PanelBottomOpen size={13} />}
          </button>
          <button
            onClick={() => { setShowProjectModal(true); fetchRecentProjects().then(setRecentProjects) }}
            className="p-1.5 rounded transition-colors"
            style={{ color: 'rgba(120,90,35,0.6)' }}
            onMouseEnter={e => (e.currentTarget.style.color = '#c9a030')}
            onMouseLeave={e => (e.currentTarget.style.color = 'rgba(120,90,35,0.6)')}
            title={`Mundo: ${projectPath}`}
          >
            <FolderOpen size={13} />
          </button>
        </div>
      </header>

      {/* ══ Error toast ════════════════════════════════════════════════════════ */}
      {fileError && (
        <div className="absolute top-14 left-1/2 -translate-x-1/2 z-50 flex items-center gap-2 px-3 py-2 rounded border text-[12px] shadow-xl font-crimson"
          style={{ background: 'rgba(201,64,64,0.10)', borderColor: 'rgba(201,64,64,0.30)', color: '#e08080' }}>
          <span>✗</span>
          {fileError}
          <button onClick={() => setFileError(null)} className="ml-1 opacity-60 hover:opacity-100">
            <X size={11} />
          </button>
        </div>
      )}

      {/* ══ Main Layout ════════════════════════════════════════════════════════ */}
      <div className="flex flex-1 overflow-hidden">

        {/* Tomes — File Explorer */}
        {showFileTree && (
          <aside className="w-52 flex-shrink-0 overflow-hidden flex flex-col"
            style={{ borderRight: '1px solid rgba(160,120,40,0.22)' }}>
            <FileExplorer
              activeFile={activeFile}
              onFileSelect={openFile}
              refreshTrigger={fileTreeRefresh}
            />
          </aside>
        )}

        {/* Center column */}
        <div className="flex flex-col flex-1 overflow-hidden min-w-0">

          {/* Monaco Editor */}
          <div
            className="overflow-hidden flex-shrink-0"
            style={{ height: showOutput ? (fileCards.length > 0 ? '50%' : '60%') : '100%' }}
          >
            <MonacoEditor
              path={activeFile}
              content={fileContent}
              onChange={handleContentChange}
              onSave={handleSave}
              saving={saving}
            />
          </div>

          {/* Pergaminos Alterados — River of Cards */}
          {fileCards.length > 0 && (
            <div className="flex-shrink-0 overflow-hidden"
              style={{ borderTop: '1px solid rgba(160,120,40,0.18)' }}>
              <div className="flex items-center gap-1.5 px-3 py-1.5"
                style={{ borderBottom: '1px solid rgba(160,120,40,0.12)' }}>
                <span className="text-[9px] font-cinzel uppercase tracking-widest"
                  style={{ color: 'rgba(160,120,40,0.5)' }}>
                  Pergaminos Alterados
                </span>
                <span className="text-[9px] font-mono"
                  style={{ color: 'rgba(201,160,48,0.45)' }}>
                  {fileCards.length} tomo{fileCards.length !== 1 ? 's' : ''}
                </span>
                <button onClick={() => setFileCards([])} className="ml-auto transition-colors"
                  style={{ color: 'rgba(120,90,35,0.5)' }}
                  onMouseEnter={e => (e.currentTarget.style.color = 'rgba(201,64,64,0.7)')}
                  onMouseLeave={e => (e.currentTarget.style.color = 'rgba(120,90,35,0.5)')}>
                  <X size={10} />
                </button>
              </div>
              <div className="flex gap-2 p-2 overflow-x-auto" style={{ scrollbarWidth: 'thin' }}>
                {fileCards.map((card) => (
                  <RiverCard key={card.path} card={card} onOpen={openFile} />
                ))}
              </div>
            </div>
          )}

          {/* Bottom panel — ATB Log / Workshop */}
          {showOutput && (
            <div className="flex flex-col overflow-hidden min-h-0"
              style={{ borderTop: '1px solid rgba(160,120,40,0.18)', flex: '1 1 0' }}>
              {/* Tab bar */}
              <div className="flex items-center flex-shrink-0"
                style={{ borderBottom: '1px solid rgba(160,120,40,0.18)', background: 'rgba(12,17,40,0.8)' }}>
                <button
                  onClick={() => setBottomPanel('console')}
                  className="flex items-center gap-1.5 px-3 py-1.5 text-[11px] font-cinzel border-b-2 transition-colors tracking-wide"
                  style={{
                    color:        bottomPanel === 'console' ? '#c9a030' : 'rgba(120,90,35,0.6)',
                    borderColor:  bottomPanel === 'console' ? 'rgba(201,160,48,0.55)' : 'transparent',
                  }}>
                  <PanelBottomOpen size={11} />
                  ATB Log
                  {events.length > 0 && (
                    <span className="text-[9px] font-mono" style={{ color: 'rgba(120,90,35,0.5)' }}>
                      {events.length}
                    </span>
                  )}
                </button>
                <button
                  onClick={() => setBottomPanel('terminal')}
                  className="flex items-center gap-1.5 px-3 py-1.5 text-[11px] font-cinzel border-b-2 transition-colors tracking-wide"
                  style={{
                    color:       bottomPanel === 'terminal' ? '#c9a030' : 'rgba(120,90,35,0.6)',
                    borderColor: bottomPanel === 'terminal' ? 'rgba(201,160,48,0.55)' : 'transparent',
                  }}>
                  <TerminalSquare size={11} />
                  Workshop
                </button>
                {/* Gil cost badge */}
                {runCost > 0 && (
                  <div className="ml-auto px-2 py-1 text-[10px] font-mono flex-shrink-0"
                    style={{ color: runCost > 0.1 ? '#c9a030' : 'rgba(201,160,48,0.45)' }}>
                    🪙 {runCost.toFixed(4)} Gil
                  </div>
                )}
              </div>
              <div className="flex-1 overflow-hidden min-h-0">
                {bottomPanel === 'console'
                  ? <OutputConsole events={events} onClear={() => setEvents([])} />
                  : <Terminal />
                }
              </div>
            </div>
          )}
        </div>

        {/* Party Panel — Agent */}
        {showAgentPanel && (
          <aside className="w-64 flex-shrink-0 overflow-hidden flex flex-col"
            style={{ borderLeft: '1px solid rgba(160,120,40,0.22)' }}>
            <AgentPanel
              isRunning={isRunning}
              activeModel={activeModel}
              activeProvider={activeProvider}
              activeTool={activeTool}
              activeFile={activeFile}
              refreshTrigger={agentRefresh}
              onModelSelect={handleModelSelect}
              onFileRestored={handleFileRestored}
            />
          </aside>
        )}
      </div>

      {/* ══ Status Bar ═════════════════════════════════════════════════════════ */}
      <footer className="flex items-center justify-between px-3 py-0.5 flex-shrink-0 h-[22px]"
        style={{ background: 'rgba(201,160,48,0.03)', borderTop: '1px solid rgba(201,160,48,0.08)' }}>
        <div className="flex items-center gap-3">
          <span className="text-[10px] font-mono truncate max-w-xs"
            style={{ color: 'rgba(201,160,48,0.45)' }}>
            {activeFile ?? 'sin pergamino'}{isDirty ? ' ◆' : ''}
          </span>
          {isRunning && (
            <span className="flex items-center gap-1.5 text-[10px] font-cinzel"
              style={{ color: 'rgba(201,160,48,0.6)' }}>
              <span className="text-[9px]">ATB</span>
              <span className="atb-track"><span className="atb-fill" /></span>
              <span className="font-mono text-[9px]">Invocando… Kupo~!</span>
            </span>
          )}
        </div>
        <div className="flex items-center gap-3">
          {sessionCost > 0 && (
            <span className="text-[10px] font-mono" style={{ color: 'rgba(201,160,48,0.38)' }}>
              🪙 {sessionCost.toFixed(4)} Gil
            </span>
          )}
          {activeModel && (
            <span className="text-[10px] font-mono" style={{ color: 'rgba(120,90,35,0.6)' }}>
              ✦ {activeModel.split('/').pop()}
            </span>
          )}
          <span className="text-[10px] font-cinzel tracking-wider" style={{ color: 'rgba(90,66,30,0.5)' }}>
            Crystal Swarm ✦ v3.0
          </span>
        </div>
      </footer>

      {/* ══ World Map — Project Switcher Modal ════════════════════════════════ */}
      {showProjectModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4"
          style={{ background: 'rgba(8,12,26,0.92)', backdropFilter: 'blur(8px)' }}>
          <div className="w-full max-w-md rounded overflow-hidden"
            style={{
              background:  'linear-gradient(145deg, #0e1530 0%, #0a0f24 100%)',
              border:      '1px solid rgba(180,140,40,0.35)',
              boxShadow:   '0 24px 48px rgba(0,0,0,0.6), inset 0 1px 0 rgba(201,160,48,0.06)',
            }}>
            {/* Modal header */}
            <div className="flex items-center justify-between px-4 py-3"
              style={{ borderBottom: '1px solid rgba(160,120,40,0.22)' }}>
              <div className="flex items-center gap-2">
                <span style={{ color: '#c9a030' }}>🗺</span>
                <span className="text-[12px] font-cinzel tracking-wide" style={{ color: '#c9a030' }}>
                  Seleccionar Mundo
                </span>
              </div>
              <button onClick={() => { setShowProjectModal(false); setProjectError('') }}
                style={{ color: 'rgba(160,120,40,0.5)' }}
                onMouseEnter={e => (e.currentTarget.style.color = '#c9a030')}
                onMouseLeave={e => (e.currentTarget.style.color = 'rgba(160,120,40,0.5)')}>
                <X size={13} />
              </button>
            </div>

            <div className="p-4 space-y-3">
              <p className="text-[11px] font-crimson" style={{ color: 'rgba(140,100,40,0.7)' }}>
                Mundo activo:{' '}
                <span className="font-mono" style={{ color: '#c4a870' }}>{projectPath}</span>
              </p>

              <input
                value={projectInput}
                onChange={(e) => setProjectInput(e.target.value)}
                onKeyDown={(e) => { if (e.key === 'Enter') handleSwitchProject(projectInput) }}
                placeholder="C:/ruta/al/mundo"
                className="w-full px-3 py-2 rounded text-[12px] font-mono focus:outline-none transition-colors"
                style={{
                  background:  'rgba(8,12,26,0.8)',
                  border:      '1px solid rgba(160,120,40,0.25)',
                  color:       '#c4a870',
                  caretColor:  '#c9a030',
                }}
                onFocus={e => (e.currentTarget.style.borderColor = 'rgba(201,160,48,0.45)')}
                onBlur={e  => (e.currentTarget.style.borderColor = 'rgba(160,120,40,0.25)')}
                autoFocus
              />

              {projectError && (
                <p className="text-[11px] font-mono" style={{ color: '#c94040' }}>{projectError}</p>
              )}

              {recentProjects.length > 0 && (
                <div className="space-y-1">
                  <p className="text-[9px] font-cinzel uppercase tracking-widest"
                    style={{ color: 'rgba(160,120,40,0.45)' }}>
                    Mundos recientes
                  </p>
                  <div className="max-h-40 overflow-y-auto space-y-0.5">
                    {recentProjects.map((p) => (
                      <button key={p} onClick={() => handleSwitchProject(p)}
                        className="w-full text-left px-2 py-1.5 rounded text-[11px] font-mono transition-colors"
                        style={{
                          color:      p === projectPath ? '#c9a030' : 'rgba(140,100,40,0.7)',
                          background: p === projectPath ? 'rgba(201,160,48,0.08)' : undefined,
                        }}
                        onMouseEnter={e => { if (p !== projectPath) { e.currentTarget.style.color = '#e0c878'; e.currentTarget.style.background = 'rgba(201,160,48,0.04)' } }}
                        onMouseLeave={e => { if (p !== projectPath) { e.currentTarget.style.color = 'rgba(140,100,40,0.7)'; e.currentTarget.style.background = '' } }}>
                        {p}
                      </button>
                    ))}
                  </div>
                </div>
              )}

              <button
                onClick={() => handleSwitchProject(projectInput)}
                disabled={!projectInput.trim()}
                className="w-full py-2 rounded text-[12px] font-cinzel tracking-wider disabled:opacity-40 transition-all"
                style={{ background: 'linear-gradient(135deg, rgba(201,160,48,0.85), rgba(180,130,30,0.85))', color: '#0a0f24' }}
                onMouseEnter={e => (e.currentTarget.style.boxShadow = '0 0 16px rgba(201,160,48,0.25)')}
                onMouseLeave={e => (e.currentTarget.style.boxShadow = '')}
              >
                🗺 Viajar al Mundo
              </button>
              <p className="text-[10px] font-crimson italic text-center" style={{ color: 'rgba(140,100,40,0.45)' }}>
                Se requiere un Chocobo para aplicar los cambios
              </p>
            </div>
          </div>
        </div>
      )}

      {/* ══ Approval Modal ══════════════════════════════════════════════════════ */}
      <ApprovalModal
        isOpen={!!pendingApproval}
        content={pendingApproval ?? ''}
        onApprove={handleApprove}
        onCancel={() => setPendingApproval(null)}
      />
    </div>
  )
}
