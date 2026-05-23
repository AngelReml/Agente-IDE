'use client'

import { useEffect, useRef } from 'react'
import { Trash2, Copy } from 'lucide-react'
import { OutputEvent } from '@/types'
import { cn } from '@/lib/utils'

interface Props {
  events: OutputEvent[]
  onClear: () => void
}

// Visual config per event type
const CFG: Record<string, { icon: string; cls: string; bg?: string }> = {
  tool_start:   { icon: '⟶', cls: 'text-blue-400' },
  tool_end:     { icon: '✓', cls: 'text-emerald-400' },
  model_switch: { icon: '⚡', cls: 'text-amber-400', bg: 'bg-amber-950/20' },
  error:        { icon: '✗', cls: 'text-red-400',    bg: 'bg-red-950/20' },
  done:         { icon: '●', cls: 'text-emerald-400 font-semibold' },
  info:         { icon: '◆', cls: 'text-violet-400' },
  final:        { icon: '',  cls: 'text-zinc-200' },
  token:        { icon: '',  cls: 'text-zinc-300' },
}

function Line({ event }: { event: OutputEvent }) {
  const cfg = CFG[event.type] ?? { icon: '·', cls: 'text-zinc-500' }
  if (event.type === 'token') return null // tokens accumulated separately

  return (
    <div className={cn('flex gap-2 text-[12px] leading-5 font-mono rounded px-1', cfg.bg ?? '')}>
      {cfg.icon && (
        <span className={cn('flex-shrink-0 w-3 text-center opacity-60', cfg.cls)}>{cfg.icon}</span>
      )}
      <span className={cn('whitespace-pre-wrap break-all', cfg.cls)}>
        {event.content}
      </span>
    </div>
  )
}

const MAX_EVENTS = 2000

export function OutputConsole({ events, onClear }: Props) {
  const bottomRef = useRef<HTMLDivElement>(null)
  const containerRef = useRef<HTMLDivElement>(null)
  const autoScroll = useRef(true)

  // Auto-scroll on new events
  useEffect(() => {
    if (autoScroll.current) {
      bottomRef.current?.scrollIntoView({ behavior: 'auto' })
    }
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
        <div key={`tok-${tokenKey++}`} className="font-mono text-[12px] text-zinc-300 whitespace-pre-wrap break-all leading-5 px-1">
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
    <div className="flex flex-col h-full bg-black/20">
      <div className="flex items-center justify-between px-3 py-1 border-b border-[#1a1a1a] flex-shrink-0">
        <span className="text-[10px] font-semibold text-zinc-600 uppercase tracking-widest">Output</span>
        <div className="flex gap-2">
          {events.length > MAX_EVENTS && (
            <span className="text-[10px] text-amber-500/60">
              +{events.length - MAX_EVENTS} truncados
            </span>
          )}
          <button onClick={handleCopy} className="text-zinc-700 hover:text-zinc-300 transition-colors p-0.5" title="Copiar">
            <Copy size={11} />
          </button>
          <button onClick={onClear} className="text-zinc-700 hover:text-zinc-300 transition-colors p-0.5" title="Limpiar">
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
          <div className="text-[12px] text-zinc-700 font-mono px-1">
            Swarm listo — escribe una tarea y pulsa <span className="text-violet-400">▶ Ejecutar</span>
          </div>
        ) : rendered}
        <div ref={bottomRef} />
      </div>
    </div>
  )
}
