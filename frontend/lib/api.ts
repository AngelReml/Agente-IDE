import { FileNode, GitStatus, GitCommit, ModelsResponse, OutputEvent, OutputEventType, BackupEntry, DiffSummary } from '@/types'

const API = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'

let _counter = 0
const uid = () => `e${++_counter}-${Date.now()}`

// ── Files ─────────────────────────────────────────────────────────────────────

export async function fetchFileTree(): Promise<FileNode> {
  const res = await fetch(`${API}/api/files`)
  if (!res.ok) throw new Error(`HTTP ${res.status}`)
  return res.json() as Promise<FileNode>
}

export async function fetchFileContent(path: string): Promise<string> {
  const res = await fetch(`${API}/api/file?path=${encodeURIComponent(path)}`)
  if (!res.ok) throw new Error(`HTTP ${res.status}: ${path}`)
  const data = await res.json()
  return data.content as string
}

export async function saveFileContent(path: string, content: string): Promise<void> {
  const res = await fetch(`${API}/api/file`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ path, content }),
  })
  if (!res.ok) {
    const msg = await res.text().catch(() => `HTTP ${res.status}`)
    throw new Error(msg)
  }
}

export async function deleteFile(path: string): Promise<void> {
  const res = await fetch(`${API}/api/file?path=${encodeURIComponent(path)}`, { method: 'DELETE' })
  if (!res.ok) throw new Error(`HTTP ${res.status}`)
}

// ── Git ───────────────────────────────────────────────────────────────────────

export async function fetchGitStatus(): Promise<GitStatus> {
  const res = await fetch(`${API}/api/git/status`)
  if (!res.ok) return { status: '', branch: 'main' }
  return res.json()
}

export async function fetchGitLog(): Promise<GitCommit[]> {
  const res = await fetch(`${API}/api/git/log?n=15`)
  if (!res.ok) return []
  const data = await res.json()
  return data.commits ?? []
}

// ── Models ────────────────────────────────────────────────────────────────────

export async function fetchModels(): Promise<ModelsResponse> {
  const res = await fetch(`${API}/api/models`)
  if (!res.ok) throw new Error(`HTTP ${res.status}`)
  return res.json()
}

export async function selectModel(modelId: string): Promise<void> {
  const res = await fetch(`${API}/api/models/select`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ model_id: modelId }),
  })
  if (!res.ok) throw new Error(`HTTP ${res.status}`)
}

// ── Swarm Task ────────────────────────────────────────────────────────────────

export async function runSwarmTask(
  task: string,
  onEvent: (event: OutputEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  const res = await fetch(`${API}/run`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ task }),
    signal,
  })

  if (!res.ok) {
    const msg = await res.text().catch(() => `HTTP ${res.status}`)
    throw new Error(msg)
  }
  if (!res.body) throw new Error('No response body')

  const reader = res.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''

  try {
    while (true) {
      if (signal?.aborted) break
      const { done, value } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true })
      const lines = buffer.split('\n')
      buffer = lines.pop() ?? ''
      for (const line of lines) {
        const trimmed = line.trim()
        if (!trimmed.startsWith('data:')) continue
        const raw = trimmed.slice(5).trim()
        if (!raw || raw === '[DONE]') continue
        try {
          const parsed = JSON.parse(raw)
          onEvent({
            id: uid(),
            type: (parsed.type ?? 'info') as OutputEventType,
            content: parsed.content ?? '',
            tool: parsed.tool,
            model: parsed.model,
            provider: parsed.provider,
            color: parsed.color,
            old_model: parsed.old_model,
            new_model: parsed.new_model,
            is_free: parsed.is_free,
            cost_usd: parsed.cost_usd,
            input_tokens: parsed.input_tokens,
            output_tokens: parsed.output_tokens,
            timestamp: Date.now(),
          })
        } catch {
          // Malformed SSE line — skip
        }
      }
    }
  } finally {
    reader.releaseLock()
  }
}

// ── Routing mode ──────────────────────────────────────────────────────────────

export async function fetchRoutingMode(): Promise<'fast' | 'power'> {
  try {
    const res = await fetch(`${API}/api/routing/mode`, { signal: AbortSignal.timeout(3000) })
    if (!res.ok) return 'fast'
    const data = await res.json()
    return data.mode === 'power' ? 'power' : 'fast'
  } catch {
    return 'fast'
  }
}

export async function setRoutingMode(mode: 'fast' | 'power'): Promise<void> {
  await fetch(`${API}/api/routing/mode`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ mode }),
  })
}

// ── Cost tracking ─────────────────────────────────────────────────────────────

export async function fetchCost(): Promise<{ run: { input_tokens: number; output_tokens: number; cost_usd: number }; session: { input_tokens: number; output_tokens: number; cost_usd: number } }> {
  try {
    const res = await fetch(`${API}/api/cost`, { signal: AbortSignal.timeout(3000) })
    if (!res.ok) return { run: { input_tokens: 0, output_tokens: 0, cost_usd: 0 }, session: { input_tokens: 0, output_tokens: 0, cost_usd: 0 } }
    return res.json()
  } catch {
    return { run: { input_tokens: 0, output_tokens: 0, cost_usd: 0 }, session: { input_tokens: 0, output_tokens: 0, cost_usd: 0 } }
  }
}

// ── Project workspace ──────────────────────────────────────────────────────────

export async function fetchProject(): Promise<{ path: string }> {
  const res = await fetch(`${API}/api/project`)
  if (!res.ok) throw new Error(`HTTP ${res.status}`)
  return res.json()
}

export async function switchProject(path: string): Promise<{ status: string; path: string; note: string }> {
  const res = await fetch(`${API}/api/project/switch`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ path }),
  })
  if (!res.ok) {
    const msg = await res.text().catch(() => `HTTP ${res.status}`)
    throw new Error(msg)
  }
  return res.json()
}

export async function fetchRecentProjects(): Promise<string[]> {
  try {
    const res = await fetch(`${API}/api/project/recents`, { signal: AbortSignal.timeout(3000) })
    if (!res.ok) return []
    const data = await res.json()
    return data.recents ?? []
  } catch {
    return []
  }
}

// ── Chat history ──────────────────────────────────────────────────────────────

export async function fetchChatContext(): Promise<{ messages: number }> {
  try {
    const res = await fetch(`${API}/api/chat/context`, { signal: AbortSignal.timeout(3000) })
    if (!res.ok) return { messages: 0 }
    return res.json()
  } catch {
    return { messages: 0 }
  }
}

export async function clearChatContext(): Promise<void> {
  await fetch(`${API}/api/chat/clear`, { method: 'POST' })
}

// ── Health ────────────────────────────────────────────────────────────────────

export async function checkHealth(): Promise<{ online: boolean; provider?: string; model?: string }> {
  try {
    const res = await fetch(`${API}/health`, { signal: AbortSignal.timeout(4000) })
    if (!res.ok) return { online: false }
    const data = await res.json()
    return { online: true, provider: data.provider, model: data.model }
  } catch {
    return { online: false }
  }
}

// ── Backup / Restore (Timeline) ───────────────────────────────────────────────

export async function fetchBackups(path: string): Promise<BackupEntry[]> {
  const res = await fetch(`${API}/api/backups?path=${encodeURIComponent(path)}`)
  if (!res.ok) return []
  const data = await res.json()
  return data.backups ?? []
}

export async function restoreFile(path: string, timestamp: number): Promise<void> {
  const res = await fetch(`${API}/api/restore`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ path, timestamp }),
  })
  if (!res.ok) {
    const msg = await res.text().catch(() => `HTTP ${res.status}`)
    throw new Error(msg)
  }
}

// ── Diff Summary ──────────────────────────────────────────────────────────────

export async function fetchDiffSummary(path: string, diff: string): Promise<DiffSummary | null> {
  try {
    const res = await fetch(`${API}/api/diff/summary`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ path, diff }),
    })
    if (!res.ok) return null
    return res.json()
  } catch {
    return null
  }
}
