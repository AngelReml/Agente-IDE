'use client'

import { useEffect, useRef, useState, useCallback, KeyboardEvent } from 'react'
import { cn } from '@/lib/utils'
import { authToken } from '@/lib/api'

const WS_URL = (process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000').replace(/^http/, 'ws')

// The browser WebSocket API can't send an Authorization header, so when the
// backend is exposed and a token is configured we pass it as a query param —
// otherwise the handshake is rejected (1008) and the terminal silently fails.
function wsTerminalUrl(): string {
  const base = `${WS_URL}/ws/terminal`
  const t = authToken()
  return t ? `${base}?token=${encodeURIComponent(t)}` : base
}

// ── ANSI colour map ──────────────────────────────────────────────────────────

const ANSI_NORMAL = ['#1a1b26','#f7768e','#9ece6a','#e0af68','#7aa2f7','#bb9af7','#7dcfff','#a9b1d6']
const ANSI_BRIGHT = ['#414868','#ff9e64','#73daca','#e0af68','#7aa2f7','#bb9af7','#b4f9f8','#cdd6f4']

interface Span { text: string; fg?: string; bg?: string; bold?: boolean }
type Line = Span[]

function parseAnsi(raw: string): Line[] {
  const lines: Line[] = []
  let current: Line = []
  let fg: string | undefined
  let bg: string | undefined
  let bold = false

  const flush = (text: string) => {
    if (text) current.push({ text, fg, bg, bold })
  }

  const parts = raw.split(/(\x1b\[[0-9;]*[mK]|\x1b\[2J\x1b\[H|\r\n|\r|\n)/g)

  for (const part of parts) {
    if (!part) continue

    if (part === '\r\n' || part === '\r' || part === '\n') {
      lines.push(current)
      current = []
      continue
    }

    if (part === '\x1b[2J\x1b[H') {
      lines.length = 0
      current = []
      continue
    }

    if (part.startsWith('\x1b[') && part.endsWith('m')) {
      const codes = part.slice(2, -1).split(';').map(Number)
      for (const c of codes) {
        if (c === 0)  { fg = undefined; bg = undefined; bold = false }
        else if (c === 1) bold = true
        else if (c === 22) bold = false
        else if (c >= 30 && c <= 37) fg = ANSI_NORMAL[c - 30]
        else if (c >= 90 && c <= 97) fg = ANSI_BRIGHT[c - 90]
        else if (c >= 40 && c <= 47) bg = ANSI_NORMAL[c - 40]
        else if (c === 39) fg = undefined
        else if (c === 49) bg = undefined
      }
      continue
    }

    // Strip remaining escape sequences (cursor moves etc.)
    if (part.startsWith('\x1b')) continue

    flush(part)
  }

  if (current.length) lines.push(current)
  return lines
}

// ── Component ────────────────────────────────────────────────────────────────

interface Props { className?: string }

export function Terminal({ className }: Props) {
  const [lines, setLines]       = useState<Line[]>([])
  const [input, setInput]       = useState('')
  const [history, setHistory]   = useState<string[]>([])
  const [histIdx, setHistIdx]   = useState(-1)
  const [connected, setConnected] = useState(false)
  const wsRef   = useRef<WebSocket | null>(null)
  const reconnectTimer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const scrollRef = useRef<HTMLDivElement>(null)
  const inputRef  = useRef<HTMLInputElement>(null)

  const appendRaw = useCallback((text: string) => {
    const newLines = parseAnsi(text)
    setLines(prev => {
      const merged = [...prev]
      if (merged.length > 0 && newLines.length > 0) {
        // Merge first new line into last existing line
        merged[merged.length - 1] = [...merged[merged.length - 1], ...newLines[0]]
        return [...merged, ...newLines.slice(1)]
      }
      return [...merged, ...newLines]
    })
  }, [])

  // Single source of truth for opening the socket (used by mount AND reconnect),
  // so handlers (incl. onerror) and the token are wired consistently.
  const openSocket = useCallback(() => {
    const ws = new WebSocket(wsTerminalUrl())
    wsRef.current = ws
    ws.onopen = () => { setConnected(true); setLines([]) }
    ws.onmessage = (e) => appendRaw(e.data as string)
    ws.onclose = () => {
      setConnected(false)
      appendRaw('\x1b[2m\r\n[Conexión cerrada — click Reconectar]\x1b[0m\r\n')
    }
    ws.onerror = () => { setConnected(false) }
  }, [appendRaw])

  useEffect(() => {
    openSocket()
    return () => {
      if (reconnectTimer.current) clearTimeout(reconnectTimer.current)
      wsRef.current?.close()
    }
  }, [openSocket])

  // Auto-scroll
  useEffect(() => {
    const el = scrollRef.current
    if (el) el.scrollTop = el.scrollHeight
  }, [lines])

  const send = useCallback((cmd: string) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({ type: 'command', cmd }))
    }
  }, [])

  const handleKeyDown = useCallback((e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter') {
      const cmd = input.trim()
      // Echo input in terminal
      appendRaw(`\x1b[90m${cmd}\x1b[0m\r\n`)
      send(cmd)
      if (cmd) setHistory(prev => [cmd, ...prev.slice(0, 99)])
      setInput('')
      setHistIdx(-1)
    } else if (e.key === 'ArrowUp') {
      e.preventDefault()
      setHistIdx(prev => {
        const next = Math.min(prev + 1, history.length - 1)
        if (history[next] !== undefined) setInput(history[next])
        return next
      })
    } else if (e.key === 'ArrowDown') {
      e.preventDefault()
      setHistIdx(prev => {
        const next = Math.max(prev - 1, -1)
        setInput(next === -1 ? '' : history[next] ?? '')
        return next
      })
    } else if (e.key === 'c' && e.ctrlKey) {
      e.preventDefault()
      wsRef.current?.send(JSON.stringify({ type: 'interrupt' }))
      appendRaw('^C\r\n')
      setInput('')
    } else if (e.key === 'l' && e.ctrlKey) {
      e.preventDefault()
      setLines([])
    }
  }, [input, history, send, appendRaw])

  const reconnect = useCallback(() => {
    wsRef.current?.close()
    if (reconnectTimer.current) clearTimeout(reconnectTimer.current)
    reconnectTimer.current = setTimeout(openSocket, 100)
  }, [openSocket])

  return (
    <div className={cn('flex flex-col h-full', className)} style={{ background: '#050609' }}>
      {/* Header */}
      <div className="flex items-center gap-2 px-3 py-1.5 border-b flex-shrink-0"
        style={{ borderColor: '#1a1c22', background: '#08090d' }}>
        <div className={cn('w-1.5 h-1.5 rounded-full flex-shrink-0 transition-colors',
          connected ? 'bg-[#00e676]' : 'bg-zinc-700')}
          style={connected ? { boxShadow: '0 0 4px #00e676' } : undefined}
        />
        <span className="text-[10px] font-mono text-zinc-600">terminal</span>
        {!connected && (
          <button onClick={reconnect}
            className="ml-1 text-[10px] font-mono text-[#00f0ff]/50 hover:text-[#00f0ff] transition-colors">
            reconectar
          </button>
        )}
        <div className="ml-auto flex items-center gap-2">
          <span className="text-[9px] font-mono text-zinc-800">Ctrl+C interrupt · Ctrl+L clear · ↑↓ history</span>
          <button onClick={() => setLines([])}
            className="text-[9px] font-mono text-zinc-700 hover:text-zinc-500 transition-colors">
            clear
          </button>
        </div>
      </div>

      {/* Output */}
      <div ref={scrollRef}
        className="flex-1 overflow-y-auto p-2 cursor-text"
        style={{ scrollbarWidth: 'thin', scrollbarColor: '#1a1c22 transparent' }}
        onClick={() => inputRef.current?.focus()}>
        <pre className="text-[12px] leading-relaxed font-mono whitespace-pre-wrap break-all m-0">
          {lines.map((line, i) => (
            <div key={i} className="min-h-[1lh]">
              {line.map((span, j) => (
                <span key={j} style={{
                  color:      span.fg,
                  background: span.bg,
                  fontWeight: span.bold ? 700 : undefined,
                }}>
                  {span.text}
                </span>
              ))}
            </div>
          ))}
        </pre>
      </div>

      {/* Input bar */}
      <div className="flex items-center border-t flex-shrink-0"
        style={{ borderColor: '#1a1c22', background: '#08090d' }}>
        <span className="px-2 text-[12px] font-mono flex-shrink-0" style={{ color: '#00f0ff66' }}>❯</span>
        <input
          ref={inputRef}
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={handleKeyDown}
          disabled={!connected}
          placeholder={connected ? 'comando…' : 'desconectado'}
          className="flex-1 bg-transparent py-1.5 pr-2 text-[12px] font-mono text-zinc-200 placeholder-zinc-800 focus:outline-none disabled:opacity-40"
          style={{ caretColor: '#00f0ff' }}
          autoComplete="off"
          spellCheck={false}
        />
      </div>
    </div>
  )
}
