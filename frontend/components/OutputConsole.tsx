'use client'

import { useEffect, useRef } from 'react'
import { Trash2, Copy } from 'lucide-react'
import { OutputEvent } from '@/types'
import { cn } from '@/lib/utils'

interface Props {
  events: OutputEvent[]
  onClear: () => void
}

// ── Event visual config — FFIX palette ───────────────────────────────────────
const CFG: Record<string, { icon: string; cls: string; bg?: string; label?: string }> = {
  tool_start:   { icon: '⟶', cls: 'text-[#c9a030]' },
  tool_end:     { icon: '✓', cls: 'text-[#5dbc6e]' },
  model_switch: { icon: '✦', cls: 'text-[#c9a030] italic', bg: 'bg-[rgba(201,160,48,0.05)]', label: 'Eidolón invocado' },
  error:        { icon: '✗', cls: 'text-[#c94040]', bg: 'bg-[rgba(201,60,60,0.05)]' },
  done:         { icon: '◆', cls: 'text-[#4abcaa] font-semibold' },
  info:         { icon: '◈', cls: 'text-[#4abcaa]' },
  context:      { icon: '🐾', cls: 'text-[#8a6840]' },
  cost:         { icon: '🪙', cls: 'text-[rgba(201,160,48,0.65)]' },
  final:        { icon: '',  cls: 'text-[#e0c878]' },
  token:        { icon: '',  cls: 'text-[#c4a870]' },
}

function Line({ event }: { event: OutputEvent }) {
  const cfg = CFG[event.type] ?? { icon: '·', cls: 'text-[#5a4228]' }
  if (event.type === 'token') return null

  // Easter egg: rename model_switch label
  let content = event.content
  if (event.type === 'model_switch' && event.new_model) {
    content = `✦ Eidolón invocado: ${event.new_model}`
  }
  // Easter egg: done says kupo
  if (event.type === 'done') {
    content = content + (content.includes('Kupo') ? '' : '  ✦ Kupo~!')
  }

  return (
    <div className={cn('flex gap-2 text-[12px] leading-5 font-mono rounded px-1 py-px', cfg.bg ?? '')}>
      {cfg.icon && (
        <span className={cn('flex-shrink-0 w-3 text-center opacity-70', cfg.cls)}>{cfg.icon}</span>
      )}
      <span className={cn('whitespace-pre-wrap break-all', cfg.cls)}>
        {content}
      </span>
    </div>
  )
}

const MAX_EVENTS = 2000

export function OutputConsole({ events, onClear }: Props) {
  const bottomRef    = useRef<HTMLDivElement>(null)
  const containerRef = useRef<HTMLDivElement>(null)
  const autoScroll   = useRef(true)

  useEffect(() => {
    if (autoScroll.current) bottomRef.current?.scrollIntoView({ behavior: 'auto' })
  }, [events.length])

  const handleScroll = () => {
    const el = containerRef.current
    if (!el) return
    autoScroll.current = el.scrollHeight - el.scrollTop - el.clientHeight < 80
  }

  const handleCopy = () => {
    const lines: string[] = []
    let tokenBuf = ''
    for (const e of events) {
      if (e.type === 'token') { tokenBuf += e.content; continue }
      if (tokenBuf) { lines.push(tokenBuf); tokenBuf = '' }
      lines.push(`[${e.type}] ${e.content}`)
    }
    if (tokenBuf) lines.push(tokenBuf)
    navigator.clipboard.writeText(lines.join('\n'))
  }

  // Render: group consecutive tokens into one block
  const rendered: React.ReactNode[] = []
  let tokenBuf = ''
  let tokenKey = 0

  const flushTokens = () => {
    if (tokenBuf) {
      rendered.push(
        <div key={`tok-${tokenKey++}`}
          className="font-mono text-[12px] text-[#c4a870] whitespace-pre-wrap break-all leading-5 px-1">
          {tokenBuf}
        </div>
      )
      tokenBuf = ''
    }
  }

  const capped = events.length > MAX_EVENTS
    ? events.slice(events.length - MAX_EVENTS)
    : events

  for (const e of capped) {
    if (e.type === 'token') {
      tokenBuf += e.content
    } else {
      flushTokens()
      rendered.push(<Line key={e.id} event={e} />)
    }
  }
  flushTokens()

  return (
    <div className="flex flex-col h-full" style={{ background: 'rgba(8,12,26,0.6)' }}>
      {/* Header */}
      <div className="flex items-center justify-between px-3 py-1.5 flex-shrink-0"
        style={{ borderBottom: '1px solid rgba(160,120,40,0.18)', background: 'rgba(12,17,40,0.6)' }}>
        <span className="text-[10px] font-cinzel tracking-widest uppercase"
          style={{ color: 'rgba(201,160,48,0.55)' }}>
          ✦ Active Time Events
        </span>
        <div className="flex gap-2 items-center">
          {events.length > MAX_EVENTS && (
            <span className="text-[10px] font-mono" style={{ color: 'rgba(201,160,48,0.45)' }}>
              +{events.length - MAX_EVENTS} truncados
            </span>
          )}
          <button onClick={handleCopy}
            className="transition-colors p-0.5"
            style={{ color: 'rgba(160,120,40,0.5)' }}
            onMouseEnter={e => (e.currentTarget.style.color = '#c9a030')}
            onMouseLeave={e => (e.currentTarget.style.color = 'rgba(160,120,40,0.5)')}
            title="Copiar al pergamino">
            <Copy size={11} />
          </button>
          <button onClick={onClear}
            className="transition-colors p-0.5"
            style={{ color: 'rgba(160,120,40,0.5)' }}
            onMouseEnter={e => (e.currentTarget.style.color = '#c94040')}
            onMouseLeave={e => (e.currentTarget.style.color = 'rgba(160,120,40,0.5)')}
            title="Limpiar diario">
            <Trash2 size={11} />
          </button>
        </div>
      </div>

      <div
        ref={containerRef}
        onScroll={handleScroll}
        className="flex-1 overflow-y-auto p-2 space-y-0.5"
      >
        {rendered.length === 0 ? (
          <div className="font-mono text-[12px] leading-relaxed px-1 py-2"
            style={{ color: 'rgba(160,120,40,0.5)' }}>
            <div>Kupo! The crystal awaits thy command...</div>
            <div className="mt-1 text-[10px]" style={{ color: 'rgba(140,100,30,0.4)' }}>
              ✦  Describe tu hazaña y pulsa{' '}
              <span style={{ color: 'rgba(201,160,48,0.7)' }}>▶ Conjurar</span>
              {' '}para comenzar.
            </div>
          </div>
        ) : rendered}
        <div ref={bottomRef} />
      </div>
    </div>
  )
}
