import { FileNode, GitStatus, GitCommit, ModelsResponse, OutputEvent, OutputEventType, BackupEntry, DiffSummary } from '@/types'

const API = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'

let _counter = 0
const uid = () => `e${++_counter}-${Date.now()}`

// ── Auth ────────────────────────────────────────────────────────────────────────
// Token is needed only when the backend is exposed beyond localhost (SWARM_AUTH_TOKEN).
// Source: NEXT_PUBLIC_SWARM_TOKEN at build time, or localStorage('swarm_token') at runtime.
export function authToken(): string | null {
  if (typeof window !== 'undefined') {
    const t = window.localStorage.getItem('swarm_token')
    if (t) return t
  }
  return process.env.NEXT_PUBLIC_SWARM_TOKEN || null
}

function headers(extra: Record<string, string> = {}): Record<string, string> {
  const t = authToken()
  return t ? { ...extra, Authorization: `Bearer ${t}` } : extra
}

const JSON_HEADERS = () => headers({ 'Content-Type': 'application/json' })

// ── Files ─────────────────────────────────────────────────────────────────────

export async function fetchFileTree(): Promise<FileNode> {
  const res = await fetch(`${API}/api/files`, { headers: headers() })
  if (!res.ok) throw new Error(`HTTP ${res.status}`)
  return res.json() as Promise<FileNode>
}

export async function fetchFileContent(path: string): Promise<string> {
  const res = await fetch(`${API}/api/file?path=${encodeURIComponent(path)}`, { headers: headers() })
  if (!res.ok) throw new Error(`HTTP ${res.status}: ${path}`)
  const data = await res.json()
  return data.content as string
}

export async function saveFileContent(path: string, content: string): Promise<void> {
  const res = await fetch(`${API}/api/file`, { method: 'POST', headers: JSON_HEADERS(), body: JSON.stringify({ path, content }) })
  if (!res.ok) throw new Error(await res.text().catch(() => `HTTP ${res.status}`))
}

export async function deleteFile(path: string): Promise<void> {
  const res = await fetch(`${API}/api/file?path=${encodeURIComponent(path)}`, { method: 'DELETE', headers: headers() })
  if (!res.ok) throw new Error(`HTTP ${res.status}`)
}

// ── Git ───────────────────────────────────────────────────────────────────────

export async function fetchGitStatus(): Promise<GitStatus> {
  const res = await fetch(`${API}/api/git/status`, { headers: headers() })
  if (!res.ok) return { status: '', branch: 'main' }
  return res.json()
}

export async function fetchGitLog(): Promise<GitCommit[]> {
  const res = await fetch(`${API}/api/git/log?n=15`, { headers: headers() })
  if (!res.ok) return []
  return (await res.json()).commits ?? []
}

export async function fetchGitDiff(path: string): Promise<string> {
  try {
    const res = await fetch(`${API}/api/git/diff?path=${encodeURIComponent(path)}`, { headers: headers() })
    if (!res.ok) return ''
    return (await res.json()).diff ?? ''
  } catch {
    return ''
  }
}

// ── Models ────────────────────────────────────────────────────────────────────

export async function fetchModels(): Promise<ModelsResponse> {
  const res = await fetch(`${API}/api/models`, { headers: headers() })
  if (!res.ok) throw new Error(`HTTP ${res.status}`)
  return res.json()
}

export async function selectModel(modelId: string): Promise<void> {
  const res = await fetch(`${API}/api/models/select`, { method: 'POST', headers: JSON_HEADERS(), body: JSON.stringify({ model_id: modelId }) })
  if (!res.ok) throw new Error(`HTTP ${res.status}`)
}

// ── Swarm Task ────────────────────────────────────────────────────────────────

export async function runSwarmTask(
  task: string,
  onEvent: (event: OutputEvent) => void,
  signal?: AbortSignal,
  sessionId: string = 'default',
  endpoint: '/run' | '/run/swarm' = '/run',
): Promise<void> {
  const res = await fetch(`${API}${endpoint}`, {
    method: 'POST', headers: JSON_HEADERS(), body: JSON.stringify({ task, session_id: sessionId }), signal,
  })
  if (!res.ok) throw new Error(await res.text().catch(() => `HTTP ${res.status}`))
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
            tool: parsed.tool, model: parsed.model, provider: parsed.provider, color: parsed.color,
            old_model: parsed.old_model, new_model: parsed.new_model, is_free: parsed.is_free,
            cost_usd: parsed.cost_usd, input_tokens: parsed.input_tokens, output_tokens: parsed.output_tokens,
            run_id: parsed.run_id,
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
    const res = await fetch(`${API}/api/routing/mode`, { headers: headers(), signal: AbortSignal.timeout(3000) })
    if (!res.ok) return 'fast'
    return (await res.json()).mode === 'power' ? 'power' : 'fast'
  } catch {
    return 'fast'
  }
}

export async function setRoutingMode(mode: 'fast' | 'power'): Promise<void> {
  await fetch(`${API}/api/routing/mode`, { method: 'POST', headers: JSON_HEADERS(), body: JSON.stringify({ mode }) })
}

// ── Cost tracking ─────────────────────────────────────────────────────────────

interface CostStats { input_tokens: number; output_tokens: number; cost_usd: number }

export async function fetchCost(): Promise<{ run: CostStats; session: CostStats }> {
  const zero = { input_tokens: 0, output_tokens: 0, cost_usd: 0 }
  try {
    const res = await fetch(`${API}/api/cost`, { headers: headers(), signal: AbortSignal.timeout(3000) })
    if (!res.ok) return { run: zero, session: zero }
    return res.json()
  } catch {
    return { run: zero, session: zero }
  }
}

// ── Project workspace ──────────────────────────────────────────────────────────

export async function fetchProject(): Promise<{ path: string }> {
  const res = await fetch(`${API}/api/project`, { headers: headers() })
  if (!res.ok) throw new Error(`HTTP ${res.status}`)
  return res.json()
}

export async function switchProject(path: string): Promise<{ status: string; path: string; note: string }> {
  const res = await fetch(`${API}/api/project/switch`, { method: 'POST', headers: JSON_HEADERS(), body: JSON.stringify({ path }) })
  if (!res.ok) throw new Error(await res.text().catch(() => `HTTP ${res.status}`))
  return res.json()
}

export async function fetchRecentProjects(): Promise<string[]> {
  try {
    const res = await fetch(`${API}/api/project/recents`, { headers: headers(), signal: AbortSignal.timeout(3000) })
    if (!res.ok) return []
    return (await res.json()).recents ?? []
  } catch {
    return []
  }
}

// ── Chat history ──────────────────────────────────────────────────────────────

export async function fetchChatContext(): Promise<{ messages: number }> {
  try {
    const res = await fetch(`${API}/api/chat/context`, { headers: headers(), signal: AbortSignal.timeout(3000) })
    if (!res.ok) return { messages: 0 }
    return res.json()
  } catch {
    return { messages: 0 }
  }
}

export async function clearChatContext(): Promise<void> {
  await fetch(`${API}/api/chat/clear`, { method: 'POST', headers: headers() })
}

// ── Plan (agentic task tracking) ───────────────────────────────────────────────

export async function fetchPlan(): Promise<string> {
  try {
    const res = await fetch(`${API}/api/plan`, { headers: headers(), signal: AbortSignal.timeout(3000) })
    if (!res.ok) return ''
    return (await res.json()).plan ?? ''
  } catch {
    return ''
  }
}

// ── Health ────────────────────────────────────────────────────────────────────

export async function checkHealth(): Promise<{ online: boolean; provider?: string; model?: string }> {
  try {
    const res = await fetch(`${API}/health`, { headers: headers(), signal: AbortSignal.timeout(4000) })
    if (!res.ok) return { online: false }
    const data = await res.json()
    return { online: true, provider: data.provider, model: data.model }
  } catch {
    return { online: false }
  }
}

// ── Backup / Restore (Timeline) ───────────────────────────────────────────────

export async function fetchBackups(path: string): Promise<BackupEntry[]> {
  const res = await fetch(`${API}/api/backups?path=${encodeURIComponent(path)}`, { headers: headers() })
  if (!res.ok) return []
  return (await res.json()).backups ?? []
}

export async function restoreFile(path: string, timestamp: number): Promise<void> {
  const res = await fetch(`${API}/api/restore`, { method: 'POST', headers: JSON_HEADERS(), body: JSON.stringify({ path, timestamp }) })
  if (!res.ok) throw new Error(await res.text().catch(() => `HTTP ${res.status}`))
}

// ── Diff Summary ──────────────────────────────────────────────────────────────

export async function fetchDiffSummary(path: string, diff: string): Promise<DiffSummary | null> {
  try {
    const res = await fetch(`${API}/api/diff/summary`, { method: 'POST', headers: JSON_HEADERS(), body: JSON.stringify({ path, diff }) })
    if (!res.ok) return null
    return res.json()
  } catch {
    return null
  }
}
