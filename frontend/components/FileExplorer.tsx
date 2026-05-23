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
          className="w-full flex items-center gap-1 py-[3px] text-left text-zinc-500 hover:text-zinc-200 hover:bg-white/5 rounded transition-colors select-none text-[12px]"
          style={{ paddingLeft: pl }}
          onClick={() => setOpen(!open)}
        >
          <span className="w-3 flex-shrink-0 text-zinc-700">
            {open ? <ChevronDown size={10} /> : <ChevronRight size={10} />}
          </span>
          <span className="mr-1 text-amber-500/80 text-[11px]">
            {open ? '📂' : '📁'}
          </span>
          <span className="truncate">{node.name}</span>
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
        'w-full flex items-center gap-1.5 py-[3px] text-[12px] rounded transition-colors truncate select-none text-left',
        isActive
          ? 'bg-violet-600/25 text-violet-200'
          : 'text-zinc-500 hover:text-zinc-200 hover:bg-white/5',
      )}
      style={{ paddingLeft: pl + 14 }}
      onClick={() => onFileSelect(node.path)}
    >
      <span className="text-[11px] flex-shrink-0">{getFileIcon(node.name, 'file')}</span>
      <span className="truncate">{node.name}</span>
    </button>
  )
}

export function FileExplorer({ activeFile, onFileSelect, refreshTrigger }: Props) {
  const [tree, setTree] = useState<FileNode | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      setTree(await fetchFileTree())
    } catch (e: any) {
      const msg = e?.message?.includes('HTTP') ? `Error ${e.message}` : 'Backend sin conexión'
      setError(msg)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { load() }, [load, refreshTrigger])

  return (
    <div className="flex flex-col h-full">
      <div className="flex items-center justify-between px-3 py-2 border-b border-[#1a1a1a] flex-shrink-0">
        <span className="text-[10px] font-semibold text-zinc-600 uppercase tracking-widest">Archivos</span>
        <button
          onClick={load}
          disabled={loading}
          className="text-zinc-700 hover:text-zinc-300 transition-colors p-0.5 rounded"
        >
          <RefreshCw size={11} className={loading ? 'animate-spin' : ''} />
        </button>
      </div>
      <div className="flex-1 overflow-y-auto py-1 px-1">
        {error && (
          <div className="text-[11px] text-red-400/80 px-3 py-2 flex items-center gap-1.5">
            <span>⚠</span> {error}
          </div>
        )}
        {!error && !tree && !loading && (
          <div className="text-[11px] text-zinc-700 px-3 py-2">Sin archivos</div>
        )}
        {tree?.children?.length === 0 && (
          <div className="text-[11px] text-zinc-700 px-3 py-2">Directorio vacío</div>
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
