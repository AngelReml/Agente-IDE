'use client'

import { useRef, useCallback, useEffect } from 'react'
import dynamic from 'next/dynamic'
import { Save, Loader2 } from 'lucide-react'
import { getLanguage } from '@/lib/utils'

const Editor = dynamic(() => import('@monaco-editor/react'), {
  ssr: false,
  loading: () => (
    <div className="flex items-center justify-center h-full bg-[#1e1e1e]">
      <Loader2 size={18} className="animate-spin text-zinc-600" />
    </div>
  ),
})

interface Props {
  path: string | null
  content: string
  onChange: (value: string) => void
  onSave: () => void
  saving?: boolean
}

const EDITOR_OPTIONS = {
  fontSize: 14,
  fontFamily: "'JetBrains Mono', 'Cascadia Code', 'Fira Code', Consolas, monospace",
  fontLigatures: true,
  minimap: { enabled: false },
  scrollBeyondLastLine: false,
  lineNumbers: 'on' as const,
  renderWhitespace: 'selection' as const,
  tabSize: 2,
  wordWrap: 'on' as const,
  automaticLayout: true,
  padding: { top: 12, bottom: 12 },
  smoothScrolling: true,
  cursorBlinking: 'smooth' as const,
  cursorSmoothCaretAnimation: 'on' as const,
  bracketPairColorization: { enabled: true },
  guides: { bracketPairs: true, indentation: true },
  renderLineHighlight: 'line' as const,
}

export function MonacoEditor({ path, content, onChange, onSave, saving }: Props) {
  const editorRef = useRef<any>(null)
  // Use a ref for onSave so the Monaco command never captures a stale closure
  const onSaveRef = useRef(onSave)
  useEffect(() => { onSaveRef.current = onSave }, [onSave])

  const handleMount = useCallback((editor: any, monaco: any) => {
    editorRef.current = editor
    editor.addCommand(
      monaco.KeyMod.CtrlCmd | monaco.KeyCode.KeyS,
      () => onSaveRef.current(),
    )
    editor.addCommand(
      monaco.KeyMod.CtrlCmd | monaco.KeyMod.Shift | monaco.KeyCode.KeyF,
      () => editor.getAction('editor.action.formatDocument')?.run(),
    )
  }, []) // empty deps — stable because onSave is behind a ref

  const language = path ? getLanguage(path) : 'plaintext'

  if (!path) {
    return (
      <div className="flex flex-col items-center justify-center h-full bg-[#0d0d0d] gap-3 select-none">
        <div className="text-6xl opacity-10">⌨️</div>
        <p className="text-sm text-zinc-600">Selecciona un archivo o ejecuta una tarea</p>
        <p className="text-xs text-zinc-700">El swarm escribirá aquí directamente</p>
      </div>
    )
  }

  return (
    <div className="flex flex-col h-full">
      <div className="flex items-center justify-between px-3 py-1.5 border-b border-[#1e1e1e] bg-[#111] flex-shrink-0">
        <div className="flex items-center gap-2 min-w-0">
          <span className="text-[12px] text-zinc-400 font-mono truncate">{path}</span>
          <span className="text-[10px] text-zinc-600 bg-[#1c1c1c] px-1.5 py-0.5 rounded flex-shrink-0">{language}</span>
        </div>
        <button
          onClick={onSave}
          disabled={saving}
          className="flex items-center gap-1 text-[11px] text-zinc-500 hover:text-zinc-200 disabled:opacity-40 transition-colors px-2 py-1 rounded hover:bg-white/5 flex-shrink-0"
        >
          {saving ? <Loader2 size={11} className="animate-spin" /> : <Save size={11} />}
          <span>Ctrl+S</span>
        </button>
      </div>
      <div className="flex-1 overflow-hidden">
        <Editor
          height="100%"
          language={language}
          value={content}
          onChange={(v) => onChange(v ?? '')}
          onMount={handleMount}
          theme="vs-dark"
          options={EDITOR_OPTIONS}
        />
      </div>
    </div>
  )
}
