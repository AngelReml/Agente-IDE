'use client'

import { useEffect, useState, useCallback } from 'react'
import { GitBranch, Clock, RotateCcw } from 'lucide-react'
import { fetchGitLog, fetchModels, fetchGitStatus, fetchBackups, restoreFile } from '@/lib/api'
import { GitCommit, ModelsResponse, GitStatus, Provider, BackupEntry } from '@/types'
import { cn } from '@/lib/utils'

// ── Provider visual identity ──────────────────────────────────────────────────
const PROVIDER_UI: Record<string, { label: string; color: string; letter: string }> = {
  anthropic:   { label: 'Anthropic',  color: '#CC785C', letter: 'A' },
  openai:      { label: 'OpenAI',     color: '#10A37F', letter: 'O' },
  groq:        { label: 'Groq',       color: '#F55036', letter: 'G' },
  glm:         { label: 'ZhipuAI',    color: '#2563EB', letter: 'Z' },
  gemini:      { label: 'Gemini',     color: '#4285F4', letter: 'G' },
  deepseek:    { label: 'DeepSeek',   color: '#4D6BFE', letter: 'D' },
  huggingface: { label: 'HuggingFace', color: '#FFD21E', letter: 'H' },
  openrouter:  { label: 'OpenRouter', color: '#7C3AED', letter: 'R' },
}

const AGENT_ROLES = [
  { icon: '🏗️', name: 'Architect' },
  { icon: '💻', name: 'Coder' },
  { icon: '🔍', name: 'Reviewer' },
  { icon: '🧪', name: 'Tester' },
  { icon: '🌿', name: 'Git' },
]

interface Props {
  isRunning: boolean
  activeModel: string | null
  activeProvider: Provider
  activeTool: string | null
  activeFile: string | null
  refreshTrigger: number
  onModelSelect?: (modelId: string) => void
  onFileRestored?: () => void
}

// ── Memory Sphere SVG ─────────────────────────────────────────────────────────

function MemorySphere({ isRunning, activeTool }: { isRunning: boolean; activeTool: string | null }) {
  const isResearching = activeTool === 'delegate_research' || activeTool === 'grep_search' || activeTool === 'get_semantic_map'
  const isReviewing   = activeTool === 'delegate_review'
  const isWriting     = activeTool === 'write_file'

  return (
    <div className="flex flex-col items-center gap-1.5">
      <svg width="52" height="52" viewBox="0 0 52 52" className="overflow-visible">
        <defs>
          <radialGradient id="sg-idle"   cx="50%" cy="50%" r="50%">
            <stop offset="0%"   stopColor="#00f0ff" stopOpacity="0.2" />
            <stop offset="100%" stopColor="#00f0ff" stopOpacity="0" />
          </radialGradient>
          <radialGradient id="sg-active" cx="50%" cy="50%" r="50%">
            <stop offset="0%"   stopColor="#00f0ff" stopOpacity="0.55" />
            <stop offset="100%" stopColor="#00f0ff" stopOpacity="0" />
          </radialGradient>
          <radialGradient id="sg-review" cx="50%" cy="50%" r="50%">
            <stop offset="0%"   stopColor="#7c3aed" stopOpacity="0.7" />
            <stop offset="100%" stopColor="#7c3aed" stopOpacity="0" />
          </radialGradient>
        </defs>

        {/* Outer ambient ring */}
        <circle cx="26" cy="26" r="22" fill="none" stroke="#00f0ff" strokeWidth="0.5" strokeOpacity="0.07" />

        {/* Radar sweep — visible when running */}
        {isRunning && (
          <g style={{ transformOrigin: '26px 26px', animation: 'radar-sweep 2.8s linear infinite' }}>
            <line x1="26" y1="26" x2="26" y2="4" stroke="#00f0ff" strokeWidth="1.2" strokeOpacity="0.45" strokeLinecap="round" />
            <line x1="26" y1="26" x2="26" y2="4" stroke="#00f0ff" strokeWidth="7" strokeOpacity="0.12" strokeLinecap="round" />
          </g>
        )}

        {/* Expanding rings — researching */}
        {isResearching && [0, 0.5, 1].map((delay) => (
          <circle key={delay} cx="26" cy="26" r="9" fill="none" stroke="#00f0ff" strokeWidth="1"
            style={{ animation: `radar-ring-expand 1.6s ease-out ${delay}s infinite` }} />
        ))}

        {/* Dense reviewer core */}
        {isReviewing && (
          <circle cx="26" cy="26" r="11" fill="url(#sg-review)"
            style={{ animation: 'core-breathe 1.1s ease-in-out infinite' }} />
        )}

        {/* Writing pulse */}
        {isWriting && (
          <circle cx="26" cy="26" r="11" fill="none" stroke="#ff0055" strokeWidth="1.5"
            style={{ animation: 'pulse-ring 1s ease-out infinite' }} />
        )}

        {/* Core */}
        <circle
          cx="26" cy="26" r={isRunning ? 10 : 9}
          fill={isReviewing ? 'url(#sg-review)' : isRunning ? 'url(#sg-active)' : 'url(#sg-idle)'}
          stroke="#00f0ff"
          strokeWidth={isRunning ? 1.5 : 1}
          strokeOpacity={isRunning ? 0.75 : 0.22}
          style={isRunning && !isResearching && !isReviewing && !isWriting
            ? { animation: 'core-breathe 2.8s ease-in-out infinite' } : undefined}
        />

        {/* Center dot */}
        <circle cx="26" cy="26" r="2.2"
          fill={isRunning ? '#00f0ff' : '#1a1c22'}
          style={isRunning ? { animation: 'core-breathe 1.5s ease-in-out infinite' } : undefined}
        />

        {/* Orbit particle */}
        {isRunning && (
          <circle cx="26" cy="11" r="1.8" fill="#00f0ff" fillOpacity="0.65"
            style={{ transformOrigin: '26px 26px', animation: 'orbit 3.2s linear infinite' }} />
        )}
      </svg>

      <span className="text-[9px] font-mono tracking-widest uppercase"
        style={{ color: isRunning ? '#00f0ff88' : '#3a3f52' }}>
        {isResearching ? 'Research' :
         isReviewing   ? 'Review'   :
         isWriting     ? 'Escribiendo' :
         isRunning     ? 'Ejecutando'  : 'En reposo'}
      </span>
    </div>
  )
}

// ── Timeline Component ────────────────────────────────────────────────────────

function TimelinePanel({ filePath, onRestored }: { filePath: string | null; onRestored?: () => void }) {
  const [backups, setBackups] = useState<BackupEntry[]>([])
  const [loading, setLoading] = useState(false)
  const [restoring, setRestoring] = useState<number | null>(null)

  useEffect(() => {
    if (!filePath) { setBackups([]); return }
    setLoading(true)
    fetchBackups(filePath).then(setBackups).catch(() => setBackups([])).finally(() => setLoading(false))
  }, [filePath])

  const handleRestore = useCallback(async (ts: number) => {
    if (!filePath) return
    setRestoring(ts)
    try {
      await restoreFile(filePath, ts)
      onRestored?.()
    } finally {
      setRestoring(null)
    }
  }, [filePath, onRestored])

  if (!filePath) return (
    <div className="p-4 text-[10px] text-zinc-700 font-mono leading-relaxed">
      Selecciona un archivo<br />para ver su historial
    </div>
  )

  if (loading) return <div className="p-3 text-[10px] text-zinc-600 animate-pulse font-mono">Cargando…</div>

  if (backups.length === 0) return (
    <div className="p-3 text-[10px] text-zinc-700">Sin backups para este archivo</div>
  )

  return (
    <div className="p-3">
      <div className="text-[9px] text-zinc-700 uppercase tracking-wider mb-3">
        {backups.length} snapshot{backups.length !== 1 ? 's' : ''}
      </div>
      <div className="relative pl-4">
        {/* Vertical track line */}
        <div className="absolute left-[7px] top-1 bottom-1 w-px bg-gradient-to-b from-[#00f0ff]/30 via-[#1a1c22] to-transparent" />

        <div className="space-y-3">
          {backups.slice(0, 12).map((b, i) => {
            const date = new Date(b.timestamp)
            const timeLabel = date.toLocaleTimeString('es', { hour: '2-digit', minute: '2-digit', second: '2-digit' })
            const dayLabel  = date.toLocaleDateString('es', { month: 'short', day: 'numeric' })
            const isRest    = restoring === b.timestamp
            return (
              <div key={b.timestamp} className="flex items-start gap-2 group relative">
                {/* Node */}
                <div className={cn(
                  'absolute -left-4 top-0.5 w-2 h-2 rounded-full border transition-all',
                  i === 0
                    ? 'bg-[#00f0ff]/25 border-[#00f0ff]/50 shadow-[0_0_5px_rgba(0,240,255,0.35)]'
                    : 'bg-[#0d0f14] border-[#242730] group-hover:border-[#00f0ff]/35',
                )} />
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-1.5">
                    <span className="text-[10px] font-mono text-zinc-400">{timeLabel}</span>
                    {i === 0 && <span className="text-[8px] text-[#00f0ff]/50 font-mono">latest</span>}
                  </div>
                  <div className="text-[9px] text-zinc-700">{dayLabel}</div>
                </div>
                <button
                  onClick={() => handleRestore(b.timestamp)}
                  disabled={isRest}
                  title="Restaurar"
                  className="opacity-0 group-hover:opacity-100 transition-opacity p-0.5 rounded text-zinc-600 hover:text-[#ff0055] hover:bg-[#ff0055]/10 flex-shrink-0"
                >
                  {isRest ? <span className="text-[8px] text-[#ff0055] font-mono">…</span> : <RotateCcw size={10} />}
                </button>
              </div>
            )
          })}
        </div>
      </div>
    </div>
  )
}

// ── Main component ────────────────────────────────────────────────────────────

export function AgentPanel({
  isRunning,
  activeModel,
  activeProvider,
  activeTool,
  activeFile,
  refreshTrigger,
  onModelSelect,
  onFileRestored,
}: Props) {
  const [commits, setCommits] = useState<GitCommit[]>([])
  const [gitStatus, setGitStatus] = useState<GitStatus | null>(null)
  const [models, setModels] = useState<ModelsResponse | null>(null)
  const [activeRoleIdx, setActiveRoleIdx] = useState(0)
  const [tab, setTab] = useState<'swarm' | 'git' | 'models' | 'time'>('swarm')

  useEffect(() => {
    if (!isRunning) return
    const id = setInterval(() => setActiveRoleIdx((i) => (i + 1) % AGENT_ROLES.length), 2000)
    return () => clearInterval(id)
  }, [isRunning])

  useEffect(() => {
    fetchGitLog().then(setCommits).catch(() => {})
    fetchModels().then(setModels).catch(() => {})
    fetchGitStatus().then(setGitStatus).catch(() => {})
  }, [refreshTrigger])

  const providerKey = activeProvider || models?.current?.provider || 'anthropic'
  const pUI = PROVIDER_UI[providerKey ?? 'anthropic'] ?? PROVIDER_UI.openrouter
  const displayModel = activeModel ? activeModel.split('/').pop()! : (models?.current?.display ?? '–')

  const TABS = [
    { id: 'swarm'  as const, label: '⚡' },
    { id: 'git'    as const, label: '🌿' },
    { id: 'models' as const, label: '🔗' },
    { id: 'time'   as const, label: '⏱' },
  ]

  return (
    <div className="flex flex-col h-full" style={{ background: '#08090d' }}>

      {/* ── Provider badge ── */}
      <div className="flex items-center gap-3 px-3 py-3 border-b border-[#1a1c22]"
           style={{ background: `${pUI.color}09` }}>
        <div
          className="w-10 h-10 rounded-full flex items-center justify-center text-[15px] font-bold flex-shrink-0"
          style={{
            background: `${pUI.color}14`,
            color: pUI.color,
            border: `1.5px solid ${pUI.color}${isRunning ? '55' : '22'}`,
            boxShadow: isRunning ? `0 0 16px ${pUI.color}35` : 'none',
          }}
        >
          {isRunning ? <span className="animate-pulse">{pUI.letter}</span> : pUI.letter}
        </div>
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-1.5">
            <span className="text-[11px] font-semibold" style={{ color: pUI.color }}>{pUI.label}</span>
            {models?.current?.is_free && (
              <span className="text-[8px] px-1 rounded border border-[#1a1c22] text-zinc-700 uppercase tracking-wider">free</span>
            )}
          </div>
          <div className="text-[10px] text-zinc-600 font-mono truncate">{displayModel}</div>
        </div>
        <div className="w-1.5 h-1.5 rounded-full flex-shrink-0"
             style={{
               background: isRunning ? '#00f0ff' : '#1a1c22',
               boxShadow: isRunning ? '0 0 6px #00f0ff88' : 'none',
             }} />
      </div>

      {/* ── Tab bar ── */}
      <div className="flex border-b border-[#1a1c22] flex-shrink-0">
        {TABS.map(({ id, label }) => (
          <button key={id} onClick={() => setTab(id)}
            className={cn(
              'flex-1 py-1.5 text-[13px] transition-colors',
              tab === id ? 'bg-[#00f0ff]/8 border-b border-[#00f0ff]/50' : 'text-zinc-700 hover:text-zinc-500',
            )}>
            {label}
          </button>
        ))}
      </div>

      <div className="flex-1 overflow-y-auto">

        {/* ── Swarm ── */}
        {tab === 'swarm' && (
          <div className="p-3 flex flex-col items-center gap-4">
            <div className="pt-1">
              <MemorySphere isRunning={isRunning} activeTool={activeTool} />
            </div>

            <div className="grid grid-cols-5 gap-1 w-full">
              {AGENT_ROLES.map((role, idx) => {
                const active = isRunning && idx === activeRoleIdx
                return (
                  <div key={role.name} title={role.name}
                    className={cn(
                      'flex flex-col items-center gap-1 p-1.5 rounded transition-all',
                      active ? 'bg-[#00f0ff]/10 ring-1 ring-[#00f0ff]/25' : 'bg-[#0d0f14]',
                    )}>
                    <span className={cn('text-xl', active ? 'animate-bounce' : 'opacity-25')}>
                      {role.icon}
                    </span>
                    <span className={cn(
                      'text-[9px] truncate w-full text-center font-mono',
                      active ? 'text-[#00f0ff]/70' : 'text-zinc-700',
                    )}>
                      {role.name.substring(0, 4)}
                    </span>
                  </div>
                )
              })}
            </div>

            {activeTool && (
              <div className="w-full p-2 rounded border border-[#00f0ff]/20 bg-[#00f0ff]/5">
                <div className="text-[9px] text-[#00f0ff]/50 uppercase tracking-wider mb-0.5">Tool</div>
                <span className="text-[11px] text-[#00f0ff]/80 font-mono">⟶ {activeTool}</span>
              </div>
            )}
          </div>
        )}

        {/* ── Git ── */}
        {tab === 'git' && (
          <div className="p-3 space-y-3">
            {gitStatus && (
              <div className="p-2.5 rounded bg-[#0d0f14] border border-[#1a1c22]">
                <div className="flex items-center gap-2 mb-1">
                  <GitBranch size={11} className="text-[#00e676] flex-shrink-0" />
                  <span className="text-[11px] font-mono text-zinc-300">{gitStatus.branch || 'main'}</span>
                </div>
                {gitStatus.status && gitStatus.status !== 'clean' ? (
                  <pre className="text-[10px] text-[#ffab00] font-mono whitespace-pre-wrap max-h-24 overflow-y-auto">
                    {gitStatus.status.slice(0, 500)}
                  </pre>
                ) : (
                  <span className="text-[10px] text-zinc-700">Working tree clean</span>
                )}
              </div>
            )}
            <div className="text-[9px] text-zinc-700 uppercase tracking-wider">Commits</div>
            {commits.length === 0 && <div className="text-[10px] text-zinc-700">Sin commits</div>}
            {commits.slice(0, 15).map((c) => (
              <div key={c.hash} className="p-2 rounded bg-[#0d0f14] border border-[#1a1c22] hover:border-[#242730] transition-colors">
                <div className="flex gap-2">
                  <span className="text-[10px] text-[#7c3aed] font-mono flex-shrink-0">{c.hash}</span>
                  <div className="min-w-0">
                    <div className="text-[10px] text-zinc-300 truncate">{c.message}</div>
                    <div className="text-[9px] text-zinc-700">{c.date}</div>
                  </div>
                </div>
              </div>
            ))}
          </div>
        )}

        {/* ── Models ── */}
        {tab === 'models' && (
          <div className="p-3">
            <div className="text-[9px] text-zinc-700 uppercase tracking-wider mb-3">Cadena de fallback</div>
            {(['anthropic', 'openai', 'groq', 'glm', 'gemini', 'deepseek', 'huggingface', 'openrouter'] as const).map((prov) => {
              const entries = (models?.chain ?? []).filter((m) => m.provider === prov)
              if (!entries.length) return null
              const pInfo = PROVIDER_UI[prov]
              return (
                <div key={prov} className="mb-3">
                  <div className="flex items-center gap-1.5 mb-1.5">
                    <div className="w-1.5 h-1.5 rounded-full" style={{ background: pInfo.color }} />
                    <span className="text-[10px]" style={{ color: pInfo.color }}>{pInfo.label}</span>
                  </div>
                  <div className="space-y-1 pl-3">
                    {entries.map((m) => {
                      const isCurrent = m.model === (activeModel || models?.current?.model)
                      const canSelect = m.available && !isRunning && !isCurrent
                      return (
                        <div key={m.model}
                          onClick={() => canSelect && onModelSelect?.(m.model)}
                          className={cn(
                            'flex items-center gap-2 px-2 py-1 rounded text-[10px] border transition-all',
                            !m.available ? 'border-[#1a1c22] opacity-20' :
                            isCurrent    ? 'border-[#00f0ff]/30 bg-[#00f0ff]/8' :
                            canSelect    ? 'border-[#1a1c22] bg-[#0d0f14] hover:border-[#00f0ff]/30 hover:bg-[#00f0ff]/5 cursor-pointer' :
                                           'border-[#1a1c22] bg-[#0d0f14]',
                          )}>
                          <span className="w-1.5 h-1.5 rounded-full flex-shrink-0"
                            style={{
                              background: !m.available ? '#1a1c22' : isCurrent ? '#00f0ff' : '#242730',
                              boxShadow: isCurrent ? '0 0 4px #00f0ff' : 'none',
                            }} />
                          <span className={cn('font-mono truncate flex-1', isCurrent ? 'text-zinc-200' : 'text-zinc-500')}>
                            {m.display}
                          </span>
                          {m.is_free && (
                            <span className="text-[7px] text-zinc-700 border border-[#1a1c22] px-1 rounded flex-shrink-0">FREE</span>
                          )}
                          {isCurrent && m.available && (
                            <span className="text-[8px] text-[#00f0ff]/60 flex-shrink-0">● activo</span>
                          )}
                        </div>
                      )
                    })}
                  </div>
                </div>
              )
            })}
          </div>
        )}

        {/* ── Timeline ── */}
        {tab === 'time' && (
          <div>
            <div className="flex items-center gap-1.5 px-3 py-2 border-b border-[#1a1c22]">
              <Clock size={10} className="text-zinc-700" />
              <span className="text-[9px] text-zinc-700 font-mono truncate">
                {activeFile ? activeFile.split(/[/\\]/).pop() : 'sin archivo'}
              </span>
            </div>
            <TimelinePanel filePath={activeFile} onRestored={onFileRestored} />
          </div>
        )}
      </div>
    </div>
  )
}
