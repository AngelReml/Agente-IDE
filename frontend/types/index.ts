export interface FileNode {
  name: string
  type: 'file' | 'directory'
  path: string
  children?: FileNode[]
}

export type OutputEventType =
  | 'token'
  | 'tool_start'
  | 'tool_end'
  | 'model_switch'
  | 'error'
  | 'done'
  | 'info'
  | 'final'
  | 'context'
  | 'cost'
  | 'run'
  | 'plan'

export interface OutputEvent {
  id: string
  type: OutputEventType
  content: string
  tool?: string
  model?: string
  provider?: string
  color?: string
  old_model?: string
  new_model?: string
  is_free?: boolean
  cost_usd?: number
  input_tokens?: number
  output_tokens?: number
  run_id?: string
  subtask?: string
  path?: string                 // structured file path for file tools
  needs_confirmation?: boolean  // structured flag for "confirmation required"
  timestamp: number
}

export type Provider =
  | 'anthropic' | 'openai' | 'groq'
  | 'glm' | 'gemini' | 'deepseek'
  | 'huggingface' | 'openrouter'
  | null

export interface ModelInfo {
  provider: Provider
  model: string
  display: string
  is_free: boolean
  color: string
  available?: boolean
}

export interface ModelsResponse {
  current: ModelInfo
  chain: (ModelInfo & { available: boolean })[]
}

export interface GitStatus {
  status: string
  branch: string
}

export interface GitCommit {
  hash: string
  message: string
  author: string
  date: string
}

/** A modified file card in the river */
export interface FileCard {
  path: string
  filename: string
  timestamp: number
  summary?: DiffSummary
  loadingSummary: boolean
}

/** Structured diff summary from the backend */
export interface DiffSummary {
  resumen_humano: string
  cambios_tecnicos: string[]
  nivel_riesgo: 'bajo' | 'medio' | 'alto'
  componentes: string[]
  stats: {
    lines_added: number
    lines_removed: number
    hunks: number
  }
}

/** Backup entry for the timeline */
export interface BackupEntry {
  timestamp: number
  backup_path: string
}
