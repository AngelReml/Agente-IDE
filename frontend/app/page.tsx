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
import { fetchFileContent, saveFileContent, runSwarmTask, checkHealth, selectModel, fetchChatContext, clearChatContext, fetchProject, switchProject, fetchRecentProjects, fetchRoutingMode, setRoutingMode } from '@/lib/api'
import { cn } from '@/lib/utils'

const MAX_EVENTS = 4000

// ── River of Cards component ─────────────────────────────────────────────────

function RiverCard({ card, onOpen }: { card: FileCard; onOpen: (path: string) => void }) {
  const risk = card.summary?.nivel_riesgo
  const isHighRisk = risk === 'alto'
  const isMedRisk  = risk === 'medio'

  return (
    <div
      onClick={() => onOpen(card.path)}
      className={cn(
        'file-card flex-shrink-0 w-48 rounded-lg border cursor-pointer transition-all group',
        'bg-[#08090d]/80 backdrop-blur-sm',
        isHighRisk ? 'border-[#ff0055]/25 hover:border-[#ff0055]/50' :
        isMedRisk  ? 'border-[#ffab00]/25 hover:border-[#ffab00]/50' :
                     'border-[#1a1c22] hover:border-[#00f0ff]/30',
        isHighRisk && 'shadow-[0_0_16px_rgba(255,0,85,0.08)]',
      )}
    >
      <div className="p-2.5">
        {/* Filename */}
        <div className="flex items-center gap-1.5 mb-1.5">
          <div className={cn(
            'w-1.5 h-1.5 rounded-full flex-shrink-0',
            card.loadingSummary ? 'bg-[#ffab00] animate-pulse' : 'bg-[#00f0ff]',
          )} style={!card.loadingSummary ? { boxShadow: '0 0 4px #00f0ff' } : undefined} />
          <span className="text-[11px] font-mono text-zinc-300 truncate" title={card.path}>
            {card.filename}
          </span>
        </div>

        {/* Summary or loading */}
        {card.loadingSummary ? (
          <div className="text-[10px] text-zinc-600 animate-pulse">Analizando…</div>
        ) : card.summary ? (
          <p className="text-[10px] text-zinc-500 leading-relaxed line-clamp-2">
            {card.summary.resumen_humano}
          </p>
        ) : (
          <p className="text-[10px] text-zinc-600">Archivo modificado</p>
        )}

        {/* Stats row */}
        <div className="flex items-center gap-2 mt-2 pt-1.5 border-t border-[#1a1c22]">
          {card.summary?.stats ? (
            <>
              <span className="text-[9px] font-mono text-[#00e676]">+{card.summary.stats.lines_added}</span>
              <span className="text-[9px] font-mono text-[#ff0055]">-{card.summary.stats.lines_removed}</span>
            </>
          ) : null}
          <span className="text-[9px] text-zinc-700 ml-auto">
            {new Date(card.timestamp).toLocaleTimeString('es', { hour: '2-digit', minute: '2-digit', second: '2-digit' })}
          </span>
        </div>
      </div>

      {/* Risk pill */}
      {risk && (
        <div className={cn(
          'px-2 py-0.5 text-[8px] font-mono uppercase tracking-widest border-t',
          isHighRisk ? 'text-[#ff0055]/70 border-[#ff0055]/15 bg-[#ff0055]/5' :
          isMedRisk  ? 'text-[#ffab00]/70 border-[#ffab00]/15 bg-[#ffab00]/5' :
                       'text-[#00f0ff]/50 border-[#1a1c22] bg-transparent',
        )}>
          {risk} riesgo
        </div>
      )}
    </div>
  )
}

// ── Main Page ────────────────────────────────────────────────────────────────

export default function SwarmIDE() {
  // Editor state
  const [activeFile, setActiveFile]     = useState<string | null>(null)
  const [fileContent, setFileContent]   = useState('')
  const [isDirty, setIsDirty]           = useState(false)
  const [saving, setSaving]             = useState(false)
  const [fileError, setFileError]       = useState<string | null>(null)

  // Task & run state
  const [task, setTask]                 = useState('')
  const [isRunning, setIsRunning]       = useState(false)
  const [activeModel, setActiveModel]   = useState<string | null>(null)
  const [activeProvider, setActiveProvider] = useState<Provider>(null)
  const [activeTool, setActiveTool]     = useState<string | null>(null)
  const abortRef = useRef<AbortController | null>(null)

  // Output
  const [events, setEvents]             = useState<OutputEvent[]>([])
  const [pendingApproval, setPendingApproval] = useState<string | null>(null)

  // River of Cards — modified files during current run
  const [fileCards, setFileCards]       = useState<FileCard[]>([])

  // Oracle scan animation
  const [oracleScan, setOracleScan]     = useState(false)

  // Stale-closure-safe active file ref
  const activeFileRef = useRef<string | null>(null)
  useEffect(() => { activeFileRef.current = activeFile }, [activeFile])

  // Sidebar/panel visibility
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

  // Cost counter (updated live from SSE events)
  const [runCost, setRunCost]         = useState(0)
  const [sessionCost, setSessionCost] = useState(0)

  // Routing mode
  const [routingMode, setRoutingModeState] = useState<'fast' | 'power'>('fast')

  // Bottom panel: 'console' | 'terminal'
  const [bottomPanel, setBottomPanel] = useState<'console' | 'terminal'>('console')

  // Project switcher
  const [projectPath, setProjectPath]       = useState('')
  const [showProjectModal, setShowProjectModal] = useState(false)
  const [projectInput, setProjectInput]     = useState('')
  const [projectError, setProjectError]     = useState('')
  const [recentProjects, setRecentProjects] = useState<string[]>([])

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

  // Sync context count with backend after each run and on mount
  useEffect(() => {
    fetchChatContext().then((r) => setContextMsgCount(r.messages))
  }, [agentRefresh])

  // Load project path and routing mode on mount
  useEffect(() => {
    fetchProject().then((r) => { setProjectPath(r.path); setProjectInput(r.path) }).catch(() => {})
    fetchRecentProjects().then(setRecentProjects).catch(() => {})
    fetchRoutingMode().then(setRoutingModeState).catch(() => {})
  }, [])

  const handleToggleMode = useCallback(async () => {
    const next: 'fast' | 'power' = routingMode === 'fast' ? 'power' : 'fast'
    setRoutingModeState(next)
    await setRoutingMode(next).catch(() => {})
  }, [routingMode])

  // Auto-dismiss file errors after 4 seconds
  useEffect(() => {
    if (!fileError) return
    const id = setTimeout(() => setFileError(null), 4000)
    return () => clearTimeout(id)
  }, [fileError])

  // Oracle scan clears after animation completes (800ms)
  useEffect(() => {
    if (!oracleScan) return
    const id = setTimeout(() => setOracleScan(false), 900)
    return () => clearTimeout(id)
  }, [oracleScan])

  // ── File operations ───────────────────────────────────────────────────────
  const openFile = useCallback(async (path: string) => {
    try {
      const content = await fetchFileContent(path)
      setActiveFile(path)
      setFileContent(content)
      setIsDirty(false)
      setFileError(null)
    } catch {
      setFileError(`No se pudo abrir: ${path}`)
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
      setFileError(`Error al guardar: ${e?.message ?? 'desconocido'}`)
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
    setOracleScan(true)
    abortRef.current = new AbortController()

    try {
      await runSwarmTask(
        currentTask,
        (event) => {
          setEvents((prev) => {
            const next = [...prev, event]
            return next.length > MAX_EVENTS ? next.slice(next.length - MAX_EVENTS) : next
          })

          // Track tool activity
          if (event.type === 'tool_start' && event.tool) {
            setActiveTool(event.tool)

            // Add a pending file card when write_file starts
            if (event.tool === 'write_file') {
              const pathMatch = event.content.match(/^(.+?)\s*\(/)
              const filePath = pathMatch ? pathMatch[1].trim() : event.content
              const filename = filePath.split(/[/\\]/).pop() ?? filePath
              const card: FileCard = {
                path: filePath,
                filename,
                timestamp: Date.now(),
                loadingSummary: true,
              }
              setFileCards((prev) => {
                // Deduplicate by path
                const without = prev.filter((c) => c.path !== filePath)
                return [...without, card]
              })
            }
          }

          // Approval gate for external filesystem operations
          if (
            event.type === 'tool_end' &&
            event.content?.includes('⚠️ CONFIRMACION REQUERIDA')
          ) {
            setPendingApproval(event.content)
            abortRef.current?.abort()
          }

          // Mark file card as written (no summary without diff, show as done)
          if (event.type === 'tool_end' && event.tool === 'write_file') {
            const pathMatch = event.content.match(/^✅\s+(.+?)\s*\(/)
            if (pathMatch) {
              const filePath = pathMatch[1].trim()
              setFileCards((prev) =>
                prev.map((c) =>
                  c.path === filePath ? { ...c, loadingSummary: false } : c
                )
              )
            } else {
              // Fallback: mark all pending as done
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
            setSessionCost((prev) => {
              // session cost only moves forward
              return Math.max(prev, event.cost_usd ?? 0)
            })
          }

          if (event.type === 'done') {
            setFileTreeRefresh((n) => n + 1)
            setAgentRefresh((n) => n + 1)
            // Refresh context count after run completes (history was updated)
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
  }, [task, isRunning])

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
      await selectModel(modelId)
      setActiveModel(modelId)
      setAgentRefresh((n) => n + 1)
      const health = await checkHealth()
      if (health.provider) setActiveProvider(health.provider as Provider)
    } catch {
      setFileError('No se pudo seleccionar el modelo')
    }
  }, [])

  const handleStop = useCallback(() => {
    abortRef.current?.abort()
    setIsRunning(false)
    setActiveTool(null)
    setFileCards((prev) => prev.map((c) => ({ ...c, loadingSummary: false })))
    setEvents((prev) => [
      ...prev,
      { id: `stop-${Date.now()}`, type: 'info', content: '⏹ Tarea detenida por el usuario', timestamp: Date.now() },
    ])
  }, [])

  const handleClearContext = useCallback(async () => {
    await clearChatContext()
    setContextMsgCount(0)
    setEvents((prev) => [
      ...prev,
      { id: `ctx-${Date.now()}`, type: 'info', content: '🗑 Contexto de sesión borrado — el próximo modelo empieza desde cero', timestamp: Date.now() },
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
      setFileError('Proyecto cambiado — reinicia el backend para aplicar')
    } catch (e: any) {
      setProjectError(e?.message ?? 'Error al cambiar proyecto')
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
      else { setOracleScan(true); handleRun() }
    }
    // Shift+Enter or Alt+Enter → insert newline (default textarea behaviour)
  }

  // ── Render ────────────────────────────────────────────────────────────────
  return (
    <div className="flex flex-col h-screen overflow-hidden" style={{ background: '#050609' }}>

      {/* ══ Oracle Bar (header) ══════════════════════════════════════════════ */}
      <header className="flex items-start gap-2 px-3 py-2 border-b flex-shrink-0 min-h-[48px]"
        style={{ borderColor: '#1a1c22', background: '#08090d' }}>

        {/* Logo */}
        <div className="flex items-center gap-2 mr-2 flex-shrink-0 mt-0.5">
          <div className="w-6 h-6 rounded flex items-center justify-center text-[12px]"
            style={{ background: 'rgba(0,240,255,0.12)', border: '1px solid rgba(0,240,255,0.2)' }}>
            ⚡
          </div>
          <span className="text-[13px] font-semibold text-zinc-400 hidden sm:block tracking-wide">
            Swarm IDE
          </span>
        </div>

        {/* Oracle Input */}
        <div className="flex-1 min-w-0 relative">
          <div className={cn(
            'flex items-center gap-2 rounded-lg border transition-all overflow-hidden',
            isRunning
              ? 'border-[#00f0ff]/25 bg-[#00f0ff]/5'
              : 'border-[#1a1c22] bg-[#0d0f14] hover:border-[#242730]',
          )}>
            {/* Scan pulse overlay */}
            {oracleScan && <div className="oracle-scan" />}

            <textarea
              ref={taskRef}
              value={task}
              rows={1}
              onChange={(e) => { setTask(e.target.value); autoResize() }}
              onKeyDown={handleKeyDown}
              placeholder="Describe la tarea…  (⏎ ejecutar · Shift+⏎ nueva línea)"
              disabled={isRunning}
              className={cn(
                'flex-1 bg-transparent px-3 py-1.5 text-[13px] placeholder-zinc-700 transition-colors min-w-0',
                'focus:outline-none resize-none leading-relaxed',
                isRunning ? 'text-zinc-500 cursor-not-allowed' : 'text-zinc-200',
              )}
              style={{ caretColor: '#00f0ff', maxHeight: '160px', overflowY: 'auto' }}
            />

            {/* Routing mode toggle */}
            <button
              onClick={handleToggleMode}
              disabled={isRunning}
              title={routingMode === 'fast'
                ? 'Modo Rápido: Groq/GLM (barato). Click para cambiar a Potente'
                : 'Modo Potente: Anthropic/OpenAI (caro). Click para cambiar a Rápido'}
              className="flex-shrink-0 self-start mt-0.5 px-2 py-1.5 rounded text-[11px] font-mono font-semibold transition-all disabled:opacity-40"
              style={routingMode === 'fast'
                ? { background: 'rgba(0,230,118,0.10)', color: '#00e676', border: '1px solid rgba(0,230,118,0.2)' }
                : { background: 'rgba(255,171,0,0.10)', color: '#ffab00', border: '1px solid rgba(255,171,0,0.25)' }}
            >
              {routingMode === 'fast' ? '⚡' : '🔥'}
            </button>

            {/* Run/Stop — mt-0.5 keeps button at top-line level when textarea grows */}
            {!isRunning ? (
              <button
                onClick={() => { setOracleScan(true); handleRun() }}
                disabled={!task.trim()}
                className={cn(
                  'flex items-center gap-1.5 px-3 py-1.5 mr-1 mt-0.5 rounded text-[12px] font-medium transition-all flex-shrink-0 self-start',
                  'disabled:opacity-30 disabled:cursor-not-allowed',
                )}
                style={{ background: 'rgba(0,240,255,0.12)', color: '#00f0ff', border: '1px solid rgba(0,240,255,0.2)' }}
              >
                <Play size={12} />
                <span className="hidden sm:inline">Ejecutar</span>
              </button>
            ) : (
              <button
                onClick={handleStop}
                className="flex items-center gap-1.5 px-3 py-1.5 mr-1 mt-0.5 rounded text-[12px] font-medium flex-shrink-0 self-start transition-all"
                style={{ background: 'rgba(255,0,85,0.12)', color: '#ff0055', border: '1px solid rgba(255,0,85,0.2)' }}
              >
                <Square size={12} />
                <span className="hidden sm:inline">Detener</span>
              </button>
            )}
          </div>
        </div>

        {/* Right controls */}
        <div className="flex items-center gap-1 ml-1 flex-shrink-0 mt-0.5">
          {/* Session context indicator + clear button */}
          {contextMsgCount > 0 && (
            <button
              onClick={handleClearContext}
              disabled={isRunning}
              title={`Contexto de sesión activo: ${contextMsgCount} mensajes. Click para borrar.`}
              className="flex items-center gap-1 px-2 py-1 rounded text-[10px] font-mono transition-all hover:opacity-80 disabled:opacity-40"
              style={{ background: 'rgba(0,240,255,0.07)', border: '1px solid rgba(0,240,255,0.15)', color: 'rgba(0,240,255,0.6)' }}
            >
              <Trash2 size={10} />
              <span className="hidden md:inline">{contextMsgCount} ctx</span>
            </button>
          )}

          {/* Backend status */}
          <div className={cn(
            'flex items-center gap-1 px-2 py-1 rounded text-[11px] font-mono',
            backendOnline === true  ? 'text-[#00e676]' :
            backendOnline === false ? 'text-[#ff3d57]' : 'text-zinc-700',
          )}>
            {backendOnline ? <Wifi size={11} /> : <WifiOff size={11} />}
            <span className="hidden md:inline text-[10px]">
              {backendOnline === null ? '…' : backendOnline ? 'online' : 'offline'}
            </span>
          </div>

          <div className="w-px h-4 mx-1" style={{ background: '#1a1c22' }} />

          <button
            onClick={() => setShowFileTree(!showFileTree)}
            className={cn('p-1.5 rounded transition-colors text-[11px]',
              showFileTree ? 'text-zinc-300' : 'text-zinc-700 hover:text-zinc-500')}
            style={showFileTree ? { background: 'rgba(0,240,255,0.06)' } : undefined}
            title="Explorador"
          >
            {showFileTree ? <ChevronLeft size={13} /> : <ChevronRight size={13} />}
          </button>
          <button
            onClick={() => setShowOutput(!showOutput)}
            className={cn('p-1.5 rounded transition-colors',
              showOutput ? 'text-zinc-300' : 'text-zinc-700 hover:text-zinc-500')}
            style={showOutput ? { background: 'rgba(0,240,255,0.06)' } : undefined}
            title="Panel inferior"
          >
            {showOutput ? <PanelBottomClose size={13} /> : <PanelBottomOpen size={13} />}
          </button>

          {/* Project switcher */}
          <button
            onClick={() => { setShowProjectModal(true); fetchRecentProjects().then(setRecentProjects) }}
            className="p-1.5 rounded transition-colors text-zinc-700 hover:text-zinc-400"
            title={`Proyecto: ${projectPath}`}
          >
            <FolderOpen size={13} />
          </button>
        </div>
      </header>

      {/* ══ Error toast ════════════════════════════════════════════════════════ */}
      {fileError && (
        <div className="absolute top-14 left-1/2 -translate-x-1/2 z-50 flex items-center gap-2 px-3 py-2 rounded-lg border text-[12px] shadow-xl"
          style={{ background: 'rgba(255,61,87,0.12)', borderColor: 'rgba(255,61,87,0.3)', color: '#ff8096' }}>
          <span>✗</span>
          {fileError}
          <button onClick={() => setFileError(null)} className="ml-1 opacity-60 hover:opacity-100">
            <X size={11} />
          </button>
        </div>
      )}

      {/* ══ Main Layout ════════════════════════════════════════════════════════ */}
      <div className="flex flex-1 overflow-hidden">

        {/* File Explorer */}
        {showFileTree && (
          <aside className="w-52 flex-shrink-0 border-r overflow-hidden flex flex-col"
            style={{ borderColor: '#1a1c22', background: '#08090d' }}>
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

          {/* ── River of Cards (live modified files) ── */}
          {fileCards.length > 0 && (
            <div className="flex-shrink-0 border-t overflow-hidden"
              style={{ borderColor: '#1a1c22', background: '#05060900' }}>
              <div className="flex items-center gap-1.5 px-3 py-1.5 border-b"
                style={{ borderColor: '#1a1c22' }}>
                <span className="text-[9px] text-zinc-700 uppercase tracking-widest font-mono">
                  Río de cambios
                </span>
                <span className="text-[9px] font-mono"
                  style={{ color: 'rgba(0,240,255,0.4)' }}>
                  {fileCards.length} archivo{fileCards.length !== 1 ? 's' : ''}
                </span>
                <button
                  onClick={() => setFileCards([])}
                  className="ml-auto text-zinc-700 hover:text-zinc-500 transition-colors"
                >
                  <X size={10} />
                </button>
              </div>
              <div className="flex gap-2 p-2 overflow-x-auto"
                style={{ scrollbarWidth: 'thin' }}>
                {fileCards.map((card) => (
                  <RiverCard key={card.path} card={card} onOpen={openFile} />
                ))}
              </div>
            </div>
          )}

          {/* Bottom panel: Console | Terminal */}
          {showOutput && (
            <div className="flex flex-col border-t overflow-hidden min-h-0"
              style={{ borderColor: '#1a1c22', flex: '1 1 0' }}>
              {/* Tab bar */}
              <div className="flex items-center border-b flex-shrink-0"
                style={{ borderColor: '#1a1c22', background: '#08090d' }}>
                <button
                  onClick={() => setBottomPanel('console')}
                  className={cn(
                    'flex items-center gap-1.5 px-3 py-1.5 text-[11px] font-medium border-b-2 transition-colors',
                    bottomPanel === 'console'
                      ? 'text-[#00f0ff] border-[#00f0ff]/50'
                      : 'text-zinc-600 border-transparent hover:text-zinc-400',
                  )}
                >
                  <PanelBottomOpen size={11} />
                  Consola
                  {events.length > 0 && (
                    <span className="text-[9px] font-mono text-zinc-700">{events.length}</span>
                  )}
                </button>
                <button
                  onClick={() => setBottomPanel('terminal')}
                  className={cn(
                    'flex items-center gap-1.5 px-3 py-1.5 text-[11px] font-medium border-b-2 transition-colors',
                    bottomPanel === 'terminal'
                      ? 'text-[#00f0ff] border-[#00f0ff]/50'
                      : 'text-zinc-600 border-transparent hover:text-zinc-400',
                  )}
                >
                  <TerminalSquare size={11} />
                  Terminal
                </button>
                {/* Cost badge */}
                {runCost > 0 && (
                  <div className="ml-auto px-2 py-1 text-[10px] font-mono flex-shrink-0"
                    style={{ color: runCost > 0.1 ? '#ffab00' : 'rgba(0,240,255,0.5)' }}>
                    run ${runCost.toFixed(4)}
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

        {/* Agent Panel */}
        {showAgentPanel && (
          <aside className="w-64 flex-shrink-0 border-l overflow-hidden flex flex-col"
            style={{ borderColor: '#1a1c22' }}>
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
      <footer className="flex items-center justify-between px-3 py-0.5 flex-shrink-0 h-[22px] border-t"
        style={{ background: 'rgba(0,240,255,0.03)', borderColor: 'rgba(0,240,255,0.08)' }}>
        <div className="flex items-center gap-3">
          <span className="text-[10px] font-mono truncate max-w-xs"
            style={{ color: 'rgba(0,240,255,0.4)' }}>
            {activeFile ?? 'sin archivo'}{isDirty ? ' ●' : ''}
          </span>
          {isRunning && (
            <span className="text-[10px] font-mono flex items-center gap-1"
              style={{ color: '#00f0ff88' }}>
              <span className="w-1.5 h-1.5 rounded-full inline-block"
                style={{ background: '#00f0ff', animation: 'core-breathe 1.2s ease-in-out infinite' }} />
              Swarm ejecutando…
            </span>
          )}
        </div>
        <div className="flex items-center gap-3">
          {sessionCost > 0 && (
            <span className="text-[10px] font-mono" style={{ color: 'rgba(255,171,0,0.4)' }}>
              sesión ${sessionCost.toFixed(4)}
            </span>
          )}
          {activeModel && (
            <span className="text-[10px] font-mono text-zinc-700">
              {activeModel.split('/').pop()}
            </span>
          )}
          <span className="text-[10px] font-mono text-zinc-800">Swarm IDE v3.0</span>
        </div>
      </footer>

      {/* ══ Project Switcher Modal ══════════════════════════════════════════════ */}
      {showProjectModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4"
          style={{ background: 'rgba(5,6,9,0.9)', backdropFilter: 'blur(8px)' }}>
          <div className="w-full max-w-md rounded-xl border overflow-hidden"
            style={{ background: '#0d0f14', borderColor: '#1a1c22' }}>
            {/* Header */}
            <div className="flex items-center justify-between px-4 py-3 border-b"
              style={{ borderColor: '#1a1c22' }}>
              <div className="flex items-center gap-2">
                <FolderOpen size={14} style={{ color: '#00f0ff' }} />
                <span className="text-[12px] font-semibold text-zinc-200">Cambiar Workspace</span>
              </div>
              <button onClick={() => { setShowProjectModal(false); setProjectError('') }}
                className="text-zinc-600 hover:text-zinc-400 transition-colors">
                <X size={13} />
              </button>
            </div>

            <div className="p-4 space-y-3">
              <p className="text-[11px] text-zinc-600">Ruta actual: <span className="font-mono text-zinc-400">{projectPath}</span></p>

              <input
                value={projectInput}
                onChange={(e) => setProjectInput(e.target.value)}
                onKeyDown={(e) => { if (e.key === 'Enter') handleSwitchProject(projectInput) }}
                placeholder="C:/ruta/al/proyecto"
                className="w-full px-3 py-2 rounded border text-[12px] font-mono text-zinc-200 bg-[#050609] focus:outline-none focus:border-[#00f0ff]/30 transition-colors"
                style={{ borderColor: '#1a1c22', caretColor: '#00f0ff' }}
                autoFocus
              />

              {projectError && (
                <p className="text-[11px] text-[#ff3d57]">{projectError}</p>
              )}

              {/* Recent projects */}
              {recentProjects.length > 0 && (
                <div className="space-y-1">
                  <p className="text-[10px] text-zinc-700 uppercase tracking-widest">Recientes</p>
                  <div className="max-h-40 overflow-y-auto space-y-0.5">
                    {recentProjects.map((p) => (
                      <button key={p} onClick={() => handleSwitchProject(p)}
                        className={cn(
                          'w-full text-left px-2 py-1.5 rounded text-[11px] font-mono transition-colors',
                          p === projectPath ? 'text-[#00f0ff] bg-[#00f0ff]/5' : 'text-zinc-500 hover:text-zinc-300 hover:bg-[#1a1c22]',
                        )}>
                        {p}
                      </button>
                    ))}
                  </div>
                </div>
              )}

              <button
                onClick={() => handleSwitchProject(projectInput)}
                disabled={!projectInput.trim()}
                className="w-full py-2 rounded text-[12px] font-semibold text-[#050609] disabled:opacity-40 transition-all"
                style={{ background: 'linear-gradient(135deg, #00f0ff, #00b8d4)' }}
              >
                Cambiar Workspace
              </button>
              <p className="text-[10px] text-zinc-700 text-center">
                Requiere reiniciar el backend para aplicar
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
