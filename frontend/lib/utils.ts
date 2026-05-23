export function getLanguage(filename: string): string {
  const ext = filename.split('.').pop()?.toLowerCase() ?? ''
  const map: Record<string, string> = {
    ts: 'typescript', tsx: 'typescript',
    js: 'javascript', jsx: 'javascript',
    mjs: 'javascript', cjs: 'javascript',
    py: 'python',
    rs: 'rust',
    go: 'go',
    java: 'java',
    kt: 'kotlin',
    cpp: 'cpp', cc: 'cpp', cxx: 'cpp',
    c: 'c', h: 'c',
    cs: 'csharp',
    rb: 'ruby',
    php: 'php',
    swift: 'swift',
    css: 'css', scss: 'scss', sass: 'scss',
    html: 'html', htm: 'html',
    json: 'json', jsonc: 'json',
    yaml: 'yaml', yml: 'yaml',
    md: 'markdown', mdx: 'markdown',
    sh: 'shell', bash: 'shell', zsh: 'shell',
    env: 'shell',
    toml: 'ini',
    xml: 'xml',
    sql: 'sql',
    dockerfile: 'dockerfile',
    txt: 'plaintext',
    lock: 'plaintext',
    gitignore: 'plaintext',
  }
  if (filename.toLowerCase() === 'dockerfile') return 'dockerfile'
  if (filename.toLowerCase() === '.gitignore') return 'plaintext'
  return map[ext] ?? 'plaintext'
}

export function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes}B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)}KB`
  return `${(bytes / 1024 / 1024).toFixed(1)}MB`
}

export function getFileIcon(name: string, type: 'file' | 'directory'): string {
  if (type === 'directory') return '📁'
  const ext = name.split('.').pop()?.toLowerCase() ?? ''
  const icons: Record<string, string> = {
    ts: '🔷', tsx: '🔷',
    js: '🟨', jsx: '🟨',
    py: '🐍',
    rs: '🦀',
    go: '🐹',
    json: '📋',
    md: '📝',
    css: '🎨', scss: '🎨',
    html: '🌐',
    sh: '⚡', bash: '⚡',
    env: '🔑',
    yml: '⚙️', yaml: '⚙️',
    sql: '🗄️',
    dockerfile: '🐳',
  }
  if (name.toLowerCase() === 'dockerfile') return '🐳'
  return icons[ext] ?? '📄'
}

export function cn(...classes: (string | undefined | null | false)[]): string {
  return classes.filter(Boolean).join(' ')
}
