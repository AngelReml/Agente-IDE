'use client'

import { useEffect, useState, useCallback } from 'react'
import { GitBranch, Clock, RotateCcw } from 'lucide-react'
import { fetchGitLog, fetchModels, fetchGitStatus, fetchBackups, restoreFile } from '@/lib/api'
import { GitCommit, ModelsResponse, GitStatus, Provider, BackupEntry } from '@/types'
import { cn } from '@/lib/utils'

// ── Provider visual identity — FFIX warm palette ──────────────────────────────
const PROVIDER_UI: Record<string, { label: string; color: string; letter: string }> = {
  anthropic:   { label: 'Anthropic',   color: '#CC785C', letter: 'A' },
  openai:      { label: 'OpenAI',      color: '#10A37F', letter: 'O' },
  groq:        { label: 'Groq',        color: '#E8954A', letter: 'G' },
  glm:         { label: 'ZhipuAI',     color: '#6B8FBE', letter: 'Z' },
  gemini:      { label: 'Gemini',      color: '#7BA8D4', letter: 'G' },
  deepseek:    { label: 'DeepSeek',    color: '#7B8FD4', letter: 'D' },
  huggingface: { label: 'HuggingFace', color: '#C9A030', letter: 'H' },
  openrouter:  { label: 'OpenRouter',  color: '#9B7ACD', letter: 'R' },
}

// ── Casting roles — FF job classes ────────────────────────────────────────────
const AGENT_ROLES = [
  { icon: '🔮', name: 'Oracle'  },   // Architect
  { icon: '🌑', name: 'Wizard'  },   // Coder (Black Mage)
  { icon: '📖', name: 'Scholar' },   // Reviewer
  { icon: '⚔️',  name: 'Knight'  },   // Tester
  { icon: '🎭', name: 'Bard'    },   // Git (chronicler)
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

// ── Crystal Orb — replaces the old Memory Sphere ─────────────────────────────
function CrystalOrb({ isRunning, activeTool }: { isRunning: boolean; activeTool: string | null }) {
  const isResearching = activeTool === 'delegate_research' || activeTool === 'grep_search' || activeTool === 'get_semantic_map'
  const isReviewing   = activeTool === 'delegate_review'
  const isWriting     = activeTool === 'write_file' || activeTool === 'edit_file'

  const coreColor  = isReviewing ? '#9B7ACD' : isRunning ? '#4abcaa' : '#2a1f10'
  const glowColor  = isReviewing ? 'rgba(155,122,205,0.4)' : 'rgba(74,188,170,0.35)'
  const ringColor  = isWriting   ? '#c94040' : isRunning ? '#c9a030' : 'rgba(160,120,40,0.12)'

  return (
    <div className="flex flex-col items-center gap-2">
      <svg width="60" height="60" viewBox="0 0 60 60" className="overflow-visible">
        <defs>
          <radialGradient id="orb-idle"   cx="40%" cy="35%" r="60%">
            <stop offset="0%"   stopColor="#2a1f10" stopOpacity="0.6" />
            <stop offset="100%" stopColor="#080c1a" stopOpacity="0" />
          </radialGradient>
          <radialGradient id="orb-active" cx="40%" cy="35%" r="60%">
            <stop offset="0%"   stopColor="#4abcaa" stopOpacity="0.65" />
            <stop offset="50%"  stopColor="#2a7a70" stopOpacity="0.35" />
            <stop offset="100%" stopColor="#080c1a" stopOpacity="0" />
          </radialGradient>
          <radialGradient id="orb-review" cx="40%" cy="35%" r="60%">
            <stop offset="0%"   stopColor="#9B7ACD" stopOpacity="0.7" />
            <stop offset="100%" stopColor="#080c1a" stopOpacity="0" />
          </radialGradient>
          <radialGradient id="orb-shine"  cx="38%" cy="28%" r="30%">
            <stop offset="0%"   stopColor="rgba(255,255,255,0.18)" />
            <stop offset="100%" stopColor="transparent" />
          </radialGradient>
          <filter id="orb-blur">
            <feGaussianBlur stdDeviation="2" />
          </filter>
        </defs>

        {/* Outer glow (when running) */}
        {isRunning && (
          <circle cx="30" cy="30" r="26" fill="none"
            stroke={ringColor} strokeWidth="0.8" strokeOpacity="0.35" />
        )}

        {/* Ambient ring */}
        <circle cx="30" cy="30" r="22" fill="none"
          stroke="rgba(180,140,40,0.15)" strokeWidth="1" strokeDasharray="4 3" />

        {/* Radar sweep — gold when running */}
        {isRunning && (
          <g style={{ transformOrigin: '30px 30px', animation: 'radar-sweep 3s linear infinite' }}>
            <line x1="30" y1="30" x2="30" y2="8"
              stroke={ringColor} strokeWidth="1.2" strokeOpacity="0.5" strokeLinecap="round" />
            <line x1="30" y1="30" x2="30" y2="8"
              stroke={ringColor} strokeWidth="8" strokeOpacity="0.08" strokeLinecap="round" />
          </g>
        )}

        {/* Expanding rings — research mode */}
        {isResearching && [0, 0.55, 1.1].map((delay, i) => (
          <circle key={i} cx="30" cy="30" r="10" fill="none"
            stroke="rgba(74,188,170,0.7)" strokeWidth="1"
            style={{ animation: `radar-ring-expand 1.8s ease-out ${delay}s infinite` }} />
        ))}

        {/* Writing pulse */}
        {isWriting && (
          <circle cx="30" cy="30" r="12" fill="none"
            stroke="#c94040" strokeWidth="1.5"
            style={{ animation: 'pulse-ring 1.1s ease-out infinite' }} />
        )}

        {/* Orb body — glow layer */}
        {isRunning && (
          <circle cx="30" cy="30" r="13" fill={glowColor} filter="url(#orb-blur)"
            style={{ animation: 'core-breathe 2.2s ease-in-out infinite' }} />
        )}

        {/* Orb body — main */}
        <circle cx="30" cy="30" r="12"
          fill={isReviewing ? 'url(#orb-review)' : isRunning ? 'url(#orb-active)' : 'url(#orb-idle)'}
          stroke="rgba(180,140,40,0.5)"
          strokeWidth={isRunning ? 1.5 : 1}
          style={isRunning && !isWriting && !isResearching && !isReviewing
            ? { animation: 'core-breathe 2.8s ease-in-out infinite' } : undefined}
        />

        {/* Specular highlight — glass-crystal effect */}
        <circle cx="30" cy="30" r="12" fill="url(#orb-shine)" />

        {/* Inner rune / core dot */}
        <circle cx="30" cy="30" r="2.5"
          fill={isRunning ? '#c9a030' : 'rgba(180,140,40,0.3)'}
          style={isRunning ? { animation: 'core-breathe 1.5s ease-in-out infinite' } : undefined}
        />

        {/* Orbiting particle — golden */}
        {isRunning && (
          <circle cx="30" cy="15" r="2" fill="#c9a030" fillOpacity="0.8"
            style={{ transformOrigin: '30px 30px', animation: 'orbit 3s linear infinite' }} />
        )}
      </svg>

      <span className="text-[9px] font-cinzel tracking-widest uppercase"
        style={{ color: isRunning ? 'rgba(201,160,48,0.65)' : 'rgba(90,66,40,0.7)' }}>
        {isResearching ? 'Seeking'    :
         isReviewing   ? 'Scrying'    :
         isWriting     ? 'Inscribing' :
         isRunning     ? 'Casting'    : 'Dormant'}
      </span>
    </div>
  )
}

// ── Timeline — Memory Crystal ─────────────────────────────────────────────────
function MemoryCrystal({ filePath, onRestored }: { filePath: string | null; onRestored?: () => void }) {
  const [backups, setBackups]     = useState<BackupEntry[]>([])
  const [loading, setLoading]     = useState(false)
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
    <div className="p-4 text-[11px] font-mono leading-relaxed" style={{ color: 'rgba(140,100,40,0.5)' }}>
      Selecciona un tomo<br />para ver su cristal de memoria
    </div>
  )

  if (loading) return (
    <div className="p-3 text-[10px] animate-pulse font-mono" style={{ color: 'rgba(201,160,48,0.4)' }}>
      Consultando el cristal…
    </div>
  )

  if (backups.length === 0) return (
    <div className="p-3 text-[10px]" style={{ color: 'rgba(140,100,40,0.5)' }}>
      Sin memorias para este pergamino
    </div>
  )

  return (
    <div className="p-3">
      <div className="text-[9px] font-cinzel uppercase tracking-wider mb-3"
        style={{ color: 'rgba(201,160,48,0.4)' }}>
        {backups.length} memoria{backups.length !== 1 ? 's' : ''} cristalizada{backups.length !== 1 ? 's' : ''}
      </div>
      <div className="relative pl-4">
        {/* Vertical timeline track */}
        <div className="absolute left-[7px] top-1 bottom-1 w-px"
          style={{ background: 'linear-gradient(to bottom, rgba(201,160,48,0.35), rgba(42,31,16,0.5), transparent)' }} />

        <div className="space-y-3">
          {backups.slice(0, 12).map((b, i) => {
            const date      = new Date(b.timestamp)
            const timeLabel = date.toLocaleTimeString('es', { hour: '2-digit', minute: '2-digit', second: '2-digit' })
            const dayLabel  = date.toLocaleDateString('es', { month: 'short', day: 'numeric' })
            const isRest    = restoring === b.timestamp
            return (
              <div key={b.timestamp} className="flex items-start gap-2 group relative">
                <div className={cn(
                  'absolute -left-4 top-0.5 w-2 h-2 rounded-full border transition-all',
                  i === 0
                    ? 'border-[rgba(201,160,48,0.6)]'
                    : 'border-[rgba(90,66,40,0.5)] group-hover:border-[rgba(201,160,48,0.4)]',
                )} style={{
                  background: i === 0 ? 'rgba(201,160,48,0.20)' : 'rgba(12,17,40,0.8)',
                  boxShadow:  i === 0 ? '0 0 5px rgba(201,160,48,0.30)' : undefined,
                }} />
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-1.5">
                    <span className="text-[10px] font-mono" style={{ color: '#c4a870' }}>{timeLabel}</span>
                    {i === 0 && <span className="text-[8px] font-cinzel" style={{ color: 'rgba(201,160,48,0.5)' }}>latest</span>}
                  </div>
                  <div className="text-[9px]" style={{ color: 'rgba(140,100,40,0.6)' }}>{dayLabel}</div>
                </div>
                <button
                  onClick={() => handleRestore(b.timestamp)}
                  disabled={isRest}
                  title="Revertir al pasado"
                  className="opacity-0 group-hover:opacity-100 transition-opacity p-0.5 rounded flex-shrink-0"
                  style={{ color: 'rgba(140,100,40,0.6)' }}
                  onMouseEnter={e => (e.currentTarget.style.color = '#c94040')}
                  onMouseLeave={e => (e.currentTarget.style.color = 'rgba(140,100,40,0.6)')}
                >
                  {isRest
                    ? <span className="text-[8px] font-mono" style={{ color: '#c94040' }}>…</span>
                    : <RotateCcw size={10} />}
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
  const [commits, setCommits]       = useState<GitCommit[]>([])
  const [gitStatus, setGitStatus]   = useState<GitStatus | null>(null)
  const [models, setModels]         = useState<ModelsResponse | null>(null)
  const [activeRoleIdx, setActiveRoleIdx] = useState(0)
  const [tab, setTab]               = useState<'swarm' | 'git' | 'models' | 'time'>('swarm')

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
  const pUI         = PROVIDER_UI[providerKey ?? 'anthropic'] ?? PROVIDER_UI.openrouter
  const displayModel = activeModel ? activeModel.split('/').pop()! : (models?.current?.display ?? '–')

  const TABS = [
    { id: 'swarm'  as const, label: '⚡', title: 'Party'    },
    { id: 'git'    as const, label: '📜', title: 'Memoria'  },
    { id: 'models' as const, label: '✦',  title: 'Eidolons' },
    { id: 'time'   as const, label: '🔮', title: 'Crystal'  },
  ]

  return (
    <div className="flex flex-col h-full" style={{ background: '#0c1128' }}>

      {/* ── Summoner / Provider badge ─────────────────────────────────────── */}
      <div className="flex items-center gap-3 px-3 py-3"
        style={{ borderBottom: '1px solid rgba(160,120,40,0.20)', background: `rgba(${hexToRgb(pUI.color)},0.04)` }}>
        <div
          className="w-10 h-10 rounded-full flex items-center justify-center text-[15px] font-bold font-cinzel flex-shrink-0 transition-all"
          style={{
            background: `rgba(${hexToRgb(pUI.color)},0.12)`,
            color:       pUI.color,
            border:      `1.5px solid rgba(${hexToRgb(pUI.color)},${isRunning ? '0.55' : '0.25'})`,
            boxShadow:   isRunning ? `0 0 14px rgba(${hexToRgb(pUI.color)},0.28)` : 'none',
          }}
        >
          {isRunning ? <span className="animate-pulse">{pUI.letter}</span> : pUI.letter}
        </div>
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-1.5">
            <span className="text-[11px] font-cinzel" style={{ color: pUI.color }}>{pUI.label}</span>
            {models?.current?.is_free && (
              <span className="text-[8px] px-1 rounded uppercase tracking-wider font-mono"
                style={{ border: '1px solid rgba(160,120,40,0.25)', color: 'rgba(160,120,40,0.6)' }}>
                free
              </span>
            )}
          </div>
          <div className="text-[10px] font-mono truncate" style={{ color: 'rgba(140,100,40,0.7)' }}>
            {displayModel}
          </div>
        </div>
        <div className="w-1.5 h-1.5 rounded-full flex-shrink-0"
          style={{
            background: isRunning ? '#c9a030' : 'rgba(60,45,20,0.8)',
            boxShadow:  isRunning ? '0 0 6px rgba(201,160,48,0.7)' : 'none',
          }} />
      </div>

      {/* ── Tab bar ── */}
      <div className="flex flex-shrink-0"
        style={{ borderBottom: '1px solid rgba(160,120,40,0.18)' }}>
        {TABS.map(({ id, label, title }) => (
          <button key={id} onClick={() => setTab(id)}
            title={title}
            className="flex-1 py-1.5 text-[13px] transition-colors"
            style={{
              color:        tab === id ? '#c9a030' : 'rgba(120,90,35,0.6)',
              background:   tab === id ? 'rgba(201,160,48,0.07)' : undefined,
              borderBottom: tab === id ? '2px solid rgba(201,160,48,0.5)' : '2px solid transparent',
            }}>
            {label}
          </button>
        ))}
      </div>

      <div className="flex-1 overflow-y-auto">

        {/* ── Party (Swarm) ── */}
        {tab === 'swarm' && (
          <div className="p-3 flex flex-col items-center gap-4">
            <div className="pt-1">
              <CrystalOrb isRunning={isRunning} activeTool={activeTool} />
            </div>

            {/* Job class grid */}
            <div className="grid grid-cols-5 gap-1 w-full">
              {AGENT_ROLES.map((role, idx) => {
                const active = isRunning && idx === activeRoleIdx
                return (
                  <div key={role.name} title={role.name}
                    className="flex flex-col items-center gap-1 p-1.5 rounded transition-all"
                    style={{
                      background:  active ? 'rgba(201,160,48,0.10)' : 'rgba(12,17,40,0.6)',
                      boxShadow:   active ? '0 0 8px rgba(201,160,48,0.15), inset 0 0 0 1px rgba(201,160,48,0.25)' : undefined,
                      border:      '1px solid',
                      borderColor: active ? 'rgba(201,160,48,0.30)' : 'rgba(60,45,20,0.5)',
                    }}>
                    <span className={cn('text-xl', active ? 'animate-bounce' : 'opacity-25')}>
                      {role.icon}
                    </span>
                    <span className="text-[8px] truncate w-full text-center font-cinzel uppercase tracking-wider"
                      style={{ color: active ? 'rgba(201,160,48,0.80)' : 'rgba(90,66,40,0.7)' }}>
                      {role.name.substring(0, 6)}
                    </span>
                  </div>
                )
              })}
            </div>

            {activeTool && (
              <div className="w-full p-2 rounded"
                style={{
                  background: 'rgba(201,160,48,0.05)',
                  border:     '1px solid rgba(201,160,48,0.22)',
                }}>
                <div className="text-[9px] font-cinzel uppercase tracking-wider mb-0.5"
                  style={{ color: 'rgba(201,160,48,0.45)' }}>
                  Hechizo activo
                </div>
                <span className="text-[11px] font-mono" style={{ color: 'rgba(201,160,48,0.75)' }}>
                  ⟶ {activeTool}
                </span>
              </div>
            )}
          </div>
        )}

        {/* ── Memoria (Git) ── */}
        {tab === 'git' && (
          <div className="p-3 space-y-3">
            {gitStatus && (
              <div className="p-2.5 rounded"
                style={{ background: 'rgba(12,17,40,0.8)', border: '1px solid rgba(160,120,40,0.20)' }}>
                <div className="flex items-center gap-2 mb-1">
                  <GitBranch size={11} style={{ color: '#5dbc6e', flexShrink: 0 }} />
                  <span className="text-[11px] font-mono" style={{ color: '#c4a870' }}>
                    {gitStatus.branch || 'main'}
                  </span>
                </div>
                {gitStatus.status && gitStatus.status !== 'clean' ? (
                  <pre className="text-[10px] font-mono whitespace-pre-wrap max-h-24 overflow-y-auto"
                    style={{ color: '#c9a030' }}>
                    {gitStatus.status.slice(0, 500)}
                  </pre>
                ) : (
                  <span className="text-[10px] font-mono" style={{ color: 'rgba(140,100,40,0.5)' }}>
                    El árbol está limpio ✦
                  </span>
                )}
              </div>
            )}
            <div className="text-[9px] font-cinzel uppercase tracking-wider"
              style={{ color: 'rgba(201,160,48,0.4)' }}>
              Crónica
            </div>
            {commits.length === 0 && (
              <div className="text-[10px] font-mono" style={{ color: 'rgba(140,100,40,0.5)' }}>
                Sin entradas en la crónica
              </div>
            )}
            {commits.slice(0, 15).map((c) => (
              <div key={c.hash} className="p-2 rounded transition-all group"
                style={{ background: 'rgba(12,17,40,0.8)', border: '1px solid rgba(90,66,30,0.35)' }}
                onMouseEnter={e => (e.currentTarget.style.borderColor = 'rgba(160,120,40,0.40)')}
                onMouseLeave={e => (e.currentTarget.style.borderColor = 'rgba(90,66,30,0.35)')}>
                <div className="flex gap-2">
                  <span className="text-[10px] font-mono flex-shrink-0" style={{ color: '#4abcaa' }}>
                    {c.hash}
                  </span>
                  <div className="min-w-0">
                    <div className="text-[10px] truncate" style={{ color: '#c4a870' }}>{c.message}</div>
                    <div className="text-[9px] font-mono" style={{ color: 'rgba(140,100,40,0.6)' }}>{c.date}</div>
                  </div>
                </div>
              </div>
            ))}
          </div>
        )}

        {/* ── Eidolons (Models) ── */}
        {tab === 'models' && (
          <div className="p-3">
            <div className="text-[9px] font-cinzel uppercase tracking-wider mb-3"
              style={{ color: 'rgba(201,160,48,0.4)' }}>
              Cadena de convocación
            </div>
            {(['anthropic','openai','groq','glm','gemini','deepseek','huggingface','openrouter'] as const).map((prov) => {
              const entries = (models?.chain ?? []).filter((m) => m.provider === prov)
              if (!entries.length) return null
              const pInfo = PROVIDER_UI[prov]
              return (
                <div key={prov} className="mb-3">
                  <div className="flex items-center gap-1.5 mb-1.5">
                    <div className="w-1.5 h-1.5 rounded-full" style={{ background: pInfo.color }} />
                    <span className="text-[10px] font-cinzel" style={{ color: pInfo.color }}>{pInfo.label}</span>
                  </div>
                  <div className="space-y-1 pl-3">
                    {entries.map((m) => {
                      const isCurrent = m.model === (activeModel || models?.current?.model)
                      const canSelect = m.available && !isRunning && !isCurrent
                      return (
                        <div key={m.model}
                          onClick={() => canSelect && onModelSelect?.(m.model)}
                          className="flex items-center gap-2 px-2 py-1 rounded text-[10px] border transition-all"
                          style={{
                            opacity:     !m.available ? 0.22 : 1,
                            borderColor: isCurrent ? 'rgba(201,160,48,0.40)' : 'rgba(60,45,20,0.50)',
                            background:  isCurrent ? 'rgba(201,160,48,0.08)' : 'rgba(12,17,40,0.8)',
                            cursor:      canSelect ? 'pointer' : 'default',
                            boxShadow:   isCurrent ? '0 0 8px rgba(201,160,48,0.10)' : undefined,
                          }}
                          onMouseEnter={e => {
                            if (canSelect) {
                              e.currentTarget.style.borderColor = 'rgba(201,160,48,0.35)'
                              e.currentTarget.style.background  = 'rgba(201,160,48,0.05)'
                            }
                          }}
                          onMouseLeave={e => {
                            if (canSelect) {
                              e.currentTarget.style.borderColor = 'rgba(60,45,20,0.50)'
                              e.currentTarget.style.background  = 'rgba(12,17,40,0.8)'
                            }
                          }}>
                          <span className="w-1.5 h-1.5 rounded-full flex-shrink-0"
                            style={{
                              background: !m.available ? 'rgba(60,45,20,0.5)' : isCurrent ? '#c9a030' : 'rgba(90,66,30,0.5)',
                              boxShadow:  isCurrent ? '0 0 4px rgba(201,160,48,0.7)' : 'none',
                            }} />
                          <span className={cn('font-mono truncate flex-1')}
                            style={{ color: isCurrent ? '#e0c878' : 'rgba(140,100,40,0.8)' }}>
                            {m.display}
                          </span>
                          {m.is_free && (
                            <span className="text-[7px] font-mono border px-1 rounded flex-shrink-0"
                              style={{ color: 'rgba(140,100,40,0.6)', borderColor: 'rgba(90,66,30,0.4)' }}>
                              FREE
                            </span>
                          )}
                          {isCurrent && m.available && (
                            <span className="text-[8px] font-cinzel flex-shrink-0"
                              style={{ color: 'rgba(201,160,48,0.65)' }}>
                              ✦ activo
                            </span>
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

        {/* ── Memory Crystal (Timeline) ── */}
        {tab === 'time' && (
          <div>
            <div className="flex items-center gap-1.5 px-3 py-2"
              style={{ borderBottom: '1px solid rgba(160,120,40,0.18)' }}>
              <Clock size={10} style={{ color: 'rgba(140,100,40,0.6)' }} />
              <span className="text-[9px] font-mono truncate" style={{ color: 'rgba(140,100,40,0.7)' }}>
                {activeFile ? activeFile.split(/[/\\]/).pop() : 'sin pergamino'}
              </span>
            </div>
            <MemoryCrystal filePath={activeFile} onRestored={onFileRestored} />
          </div>
        )}
      </div>
    </div>
  )
}

// ── Utility: hex to rgb string ────────────────────────────────────────────────
function hexToRgb(hex: string): string {
  const r = parseInt(hex.slice(1, 3), 16)
  const g = parseInt(hex.slice(3, 5), 16)
  const b = parseInt(hex.slice(5, 7), 16)
  return `${r},${g},${b}`
}
