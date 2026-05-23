'use client'

import { useState, useEffect, useCallback } from 'react'
import { RefreshCw, ChevronRight, ChevronDown } from 'lucide-react'
import { FileNode } from '@/types'
import { fetchFileTree } from '@/lib/api'
import { getFileIcon, cn } from '@/lib/utils'

interface Props {
  activeFile: string | null
  onFileSelect: (path: string) => void
  refreshTrigger: number
}

function FileNodeItem({
  node, depth, activeFile, onFileSelect,
}: {
  node: FileNode
  depth: number
  activeFile: string | null
  onFileSelect: (path: string) => void
}) {
  const [open, setOpen] = useState(depth < 2)
  const pl = 8 + depth * 14
  const isActive = activeFile === node.path

  if (node.type === 'directory') {
    return (
      <div>
        <button
          className="w-full flex items-center gap-1 py-[3px] text-left rounded transition-colors select-none text-[13px]"
          style={{
            paddingLeft: pl,
            color: 'rgba(160,120,40,0.7)',
          }}
          onMouseEnter={e => {
            e.currentTarget.style.color = '#e0c878'
            e.currentTarget.style.background = 'rgba(201,160,48,0.05)'
          }}
          onMouseLeave={e => {
            e.currentTarget.style.color = 'rgba(160,120,40,0.7)'
            e.currentTarget.style.background = ''
          }}
          onClick={() => setOpen(!open)}
        >
          <span className="w-3 flex-shrink-0" style={{ color: 'rgba(160,120,40,0.4)' }}>
            {open ? <ChevronDown size={10} /> : <ChevronRight size={10} />}
          </span>
          <span className="mr-1 text-[11px]" style={{ color: 'rgba(201,160,48,0.6)' }}>
            {open ? '📂' : '📁'}
          </span>
          <span className="truncate font-crimson">{node.name}</span>
        </button>
        {open && node.children?.map((c) => (
          <FileNodeItem
            key={c.path}
            node={c}
            depth={depth + 1}
            activeFile={activeFile}
            onFileSelect={onFileSelect}
          />
        ))}
      </div>
    )
  }

  return (
    <button
      className={cn(
        'w-full flex items-center gap-1.5 py-[3px] text-[12px] rounded transition-colors truncate select-none text-left font-mono',
      )}
      style={{
        paddingLeft: pl + 14,
        color: isActive ? '#e0c878' : 'rgba(140,105,50,0.8)',
        background: isActive ? 'rgba(201,160,48,0.10)' : undefined,
        borderLeft: isActive ? '2px solid rgba(201,160,48,0.50)' : '2px solid transparent',
      }}
      onMouseEnter={e => {
        if (!isActive) {
          e.currentTarget.style.color = '#e0c878'
          e.currentTarget.style.background = 'rgba(201,160,48,0.04)'
        }
      }}
      onMouseLeave={e => {
        if (!isActive) {
          e.currentTarget.style.color = 'rgba(140,105,50,0.8)'
          e.currentTarget.style.background = ''
        }
      }}
      onClick={() => onFileSelect(node.path)}
    >
      <span className="text-[11px] flex-shrink-0">{getFileIcon(node.name, 'file')}</span>
      <span className="truncate">{node.name}</span>
    </button>
  )
}

export function FileExplorer({ activeFile, onFileSelect, refreshTrigger }: Props) {
  const [tree, setTree]     = useState<FileNode | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError]   = useState<string | null>(null)

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      setTree(await fetchFileTree())
    } catch (e: any) {
      const msg = e?.message?.includes('HTTP') ? `Error ${e.message}` : 'Mognet sin señal'
      setError(msg)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { load() }, [load, refreshTrigger])

  return (
    <div className="flex flex-col h-full" style={{ background: '#0c1128' }}>
      {/* Header */}
      <div className="flex items-center justify-between px-3 py-2 flex-shrink-0"
        style={{ borderBottom: '1px solid rgba(160,120,40,0.18)' }}>
        <span className="text-[10px] font-cinzel tracking-widest uppercase"
          style={{ color: 'rgba(201,160,48,0.55)' }}>
          📜 Tomes
        </span>
        <button
          onClick={load}
          disabled={loading}
          className="transition-colors p-0.5 rounded"
          style={{ color: 'rgba(160,120,40,0.5)' }}
          onMouseEnter={e => (e.currentTarget.style.color = '#c9a030')}
          onMouseLeave={e => (e.currentTarget.style.color = 'rgba(160,120,40,0.5)')}
          title="Consultar el Mognet"
        >
          <RefreshCw size={11} className={loading ? 'animate-spin' : ''} />
        </button>
      </div>

      <div className="flex-1 overflow-y-auto py-1 px-1">
        {error && (
          <div className="text-[11px] px-3 py-2 flex items-center gap-1.5 font-mono"
            style={{ color: 'rgba(201,80,80,0.8)' }}>
            <span>⚠</span> {error}
          </div>
        )}
        {!error && !tree && !loading && (
          <div className="text-[11px] px-3 py-2 font-mono" style={{ color: 'rgba(140,100,40,0.5)' }}>
            Sin pergaminos
          </div>
        )}
        {tree?.children?.length === 0 && (
          <div className="text-[11px] px-3 py-2" style={{ color: 'rgba(140,100,40,0.5)' }}>
            Directorio vacío
          </div>
        )}
        {loading && !tree && (
          <div className="text-[11px] px-3 py-2 font-mono animate-pulse" style={{ color: 'rgba(201,160,48,0.4)' }}>
            Consultando el Mognet…
          </div>
        )}
        {tree?.children?.map((node) => (
          <FileNodeItem
            key={node.path}
            node={node}
            depth={0}
            activeFile={activeFile}
            onFileSelect={onFileSelect}
          />
        ))}
      </div>
    </div>
  )
}
