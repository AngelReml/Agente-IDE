'use client'

import { useState } from 'react'
import { Check, X, ChevronDown, ChevronRight, AlertTriangle, Code2, LayoutList, Building2 } from 'lucide-react'
import { cn } from '@/lib/utils'
import { DiffSummary } from '@/types'

interface Props {
  isOpen: boolean
  content: string
  summary?: DiffSummary | null
  onApprove: () => void
  onCancel: () => void
}

type Level = 'business' | 'structural' | 'expert'

export function ApprovalModal({ isOpen, content, summary, onApprove, onCancel }: Props) {
  const [activeLevel, setActiveLevel] = useState<Level>('business')
  const [expertOpen, setExpertOpen] = useState(false)

  if (!isOpen) return null

  const displayMsg = content.replace('⚠️ CONFIRMACION REQUERIDA:', '').trim()
  const risk = summary?.nivel_riesgo ?? 'alto'

  const riskColor = risk === 'alto'
    ? 'text-[#ff0055]'
    : risk === 'medio'
    ? 'text-[#ffab00]'
    : 'text-[#00e676]'

  const riskBorder = risk === 'alto'
    ? 'border-[#ff0055]/30'
    : risk === 'medio'
    ? 'border-[#ffab00]/30'
    : 'border-[#00e676]/30'

  const riskBg = risk === 'alto'
    ? 'bg-[#ff0055]/5'
    : risk === 'medio'
    ? 'bg-[#ffab00]/5'
    : 'bg-[#00e676]/5'

  const levels: { id: Level; icon: React.ReactNode; label: string }[] = [
    { id: 'business',   icon: <Building2 size={11} />,  label: 'Negocio'    },
    { id: 'structural', icon: <LayoutList size={11} />, label: 'Estructura' },
    { id: 'expert',     icon: <Code2 size={11} />,      label: 'Código'     },
  ]

  return (
    // Dimming backdrop
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 dim-overlay"
         style={{ background: 'rgba(5,6,9,0.88)', backdropFilter: 'blur(8px)' }}>

      {/* Card with magenta aura for high-risk */}
      <div className={cn(
        'w-full max-w-lg rounded-xl overflow-hidden transition-all',
        'bg-[#0d0f14] border',
        riskBorder,
        risk === 'alto' && 'magenta-aura shadow-[0_0_40px_8px_rgba(255,0,85,0.08)]',
        risk === 'medio' && 'shadow-[0_0_20px_4px_rgba(255,171,0,0.06)]',
      )}>

        {/* Header */}
        <div className={cn('flex items-center gap-3 px-5 py-3.5 border-b', riskBorder, riskBg)}>
          <AlertTriangle size={16} className={riskColor} />
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2">
              <span className="text-[12px] font-semibold text-zinc-200 uppercase tracking-wider">
                Operación de Alto Riesgo
              </span>
              <span className={cn('text-[9px] font-mono uppercase px-1.5 py-0.5 rounded border', riskColor, riskBorder, riskBg)}>
                {risk}
              </span>
            </div>
            <p className="text-[10px] text-zinc-500 mt-0.5">
              El agente solicita confirmación antes de continuar
            </p>
          </div>
        </div>

        {/* Level tabs */}
        <div className="flex border-b border-[#1a1c22]">
          {levels.map(({ id, icon, label }) => (
            <button
              key={id}
              onClick={() => setActiveLevel(id)}
              className={cn(
                'flex-1 flex items-center justify-center gap-1.5 py-2 text-[11px] font-medium transition-all',
                activeLevel === id
                  ? 'text-[#00f0ff] border-b border-[#00f0ff]/50 bg-[#00f0ff]/5'
                  : 'text-zinc-600 hover:text-zinc-400',
              )}
            >
              {icon}
              {label}
            </button>
          ))}
        </div>

        {/* Level 1 — Business */}
        {activeLevel === 'business' && (
          <div className="p-5 space-y-4">
            <p className="text-[11px] text-zinc-500 uppercase tracking-widest font-semibold">
              ¿Qué cambia en tu aplicación?
            </p>
            {summary ? (
              <p className="text-[14px] text-zinc-200 leading-relaxed">
                {summary.resumen_humano}
              </p>
            ) : (
              <p className="text-[13px] text-zinc-300 leading-relaxed">
                {displayMsg.split('\n')[0]}
              </p>
            )}
            {summary?.componentes && summary.componentes.length > 0 && (
              <div className="flex flex-wrap gap-1.5 pt-1">
                {summary.componentes.map((c, i) => (
                  <span key={i} className="text-[10px] px-2 py-0.5 rounded bg-[#121419] border border-[#1a1c22] text-zinc-400 font-mono">
                    {c}
                  </span>
                ))}
              </div>
            )}
          </div>
        )}

        {/* Level 2 — Structural */}
        {activeLevel === 'structural' && (
          <div className="p-5 space-y-3">
            <p className="text-[11px] text-zinc-500 uppercase tracking-widest font-semibold">
              Cambios técnicos
            </p>
            {summary ? (
              <ul className="space-y-2">
                {summary.cambios_tecnicos.map((c, i) => (
                  <li key={i} className="flex items-start gap-2 text-[12px] text-zinc-300">
                    <span className="text-[#00f0ff] mt-0.5 flex-shrink-0">◆</span>
                    {c}
                  </li>
                ))}
                {summary.stats && (
                  <li className="flex items-center gap-3 mt-2 pt-2 border-t border-[#1a1c22] text-[11px] font-mono">
                    <span className="text-[#00e676]">+{summary.stats.lines_added}</span>
                    <span className="text-[#ff0055]">-{summary.stats.lines_removed}</span>
                    <span className="text-zinc-600">{summary.stats.hunks} hunks</span>
                  </li>
                )}
              </ul>
            ) : (
              <pre className="text-[11px] text-zinc-300 font-mono whitespace-pre-wrap leading-relaxed bg-[#050609] rounded p-3 max-h-48 overflow-y-auto">
                {displayMsg}
              </pre>
            )}
          </div>
        )}

        {/* Level 3 — Expert (raw diff) */}
        {activeLevel === 'expert' && (
          <div className="p-5">
            <p className="text-[11px] text-zinc-500 uppercase tracking-widest font-semibold mb-3">
              Código sin procesar
            </p>
            <pre className="text-[10px] text-zinc-300 font-mono whitespace-pre-wrap leading-relaxed bg-[#050609] rounded border border-[#1a1c22] p-3 max-h-56 overflow-y-auto">
              {displayMsg}
            </pre>
          </div>
        )}

        {/* Footer */}
        <div className="flex items-center justify-between px-5 py-3.5 border-t border-[#1a1c22] bg-[#08090d]">
          <button
            onClick={onCancel}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded text-[12px] font-medium text-zinc-400 hover:text-zinc-200 hover:bg-[#ff0055]/10 hover:border-[#ff0055]/30 border border-transparent transition-all"
          >
            <X size={12} />
            Rechazar
          </button>
          <button
            onClick={onApprove}
            className="flex items-center gap-1.5 px-5 py-1.5 rounded text-[12px] font-semibold text-[#050609] transition-all"
            style={{
              background: 'linear-gradient(135deg, #00f0ff, #00b8d4)',
              boxShadow: '0 0 12px rgba(0,240,255,0.3)',
            }}
          >
            <Check size={12} />
            Confirmar Acción
          </button>
        </div>
      </div>
    </div>
  )
}
