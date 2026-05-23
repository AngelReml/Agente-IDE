import type { Config } from 'tailwindcss'

const config: Config = {
  content: [
    './app/**/*.{ts,tsx}',
    './components/**/*.{ts,tsx}',
    './lib/**/*.{ts,tsx}',
  ],
  theme: {
    extend: {
      fontFamily: {
        sans:    ['Crimson Text', 'Palatino', 'Georgia', 'serif'],
        cinzel:  ['Cinzel', 'serif'],
        crimson: ['Crimson Text', 'Georgia', 'serif'],
        mono:    ['JetBrains Mono', 'Fira Code', 'Cascadia Code', 'Consolas', 'monospace'],
      },
      colors: {
        // ── Night sky backgrounds ──────────────────────────────────────────────
        bg:       '#080c1a',
        surface: {
          DEFAULT: '#0c1128',
          1:       '#111830',
          2:       '#151e34',
          3:       '#1c2440',
          4:       '#232b4e',
        },
        // ── Old wood / leather borders ─────────────────────────────────────────
        border: {
          DEFAULT: '#2a1f10',
          gold:    '#6b4c14',
          bright:  '#b08020',
        },
        // ── Warm gold accent ───────────────────────────────────────────────────
        gold: {
          DEFAULT: '#c9a030',
          dim:     'rgba(201,160,48,0.12)',
          mid:     'rgba(201,160,48,0.25)',
          bright:  'rgba(201,160,48,0.45)',
        },
        // ── Mystic crystal teal ────────────────────────────────────────────────
        crystal: {
          DEFAULT: '#4abcaa',
          dim:     'rgba(74,188,170,0.10)',
          mid:     'rgba(74,188,170,0.22)',
          bright:  'rgba(74,188,170,0.40)',
        },
        // ── Candlelight / amber ────────────────────────────────────────────────
        candle: {
          DEFAULT: '#e0954a',
          dim:     'rgba(224,149,74,0.12)',
        },
        // ── Parchment text ─────────────────────────────────────────────────────
        parch: {
          DEFAULT: '#e0c878',
          2:       '#c4a870',
          muted:   '#8a6840',
          deep:    '#4a3820',
        },
        // ── Semantic ───────────────────────────────────────────────────────────
        success: '#5dbc6e',
        warning: '#c9a030',
        error:   '#c94040',
      },
      animation: {
        'pulse-slow':   'pulse 3s cubic-bezier(0.4, 0, 0.6, 1) infinite',
        'pulse-slower': 'pulse 4s cubic-bezier(0.4, 0, 0.6, 1) infinite',
        'blink':        'blink 1s step-end infinite',
        'orbit':        'orbit 8s linear infinite',
        'radar':        'radar-sweep 2s linear infinite',
        'atb':          'atb-charge 2.4s ease-in-out infinite',
        'candle':       'candle-flicker 3s ease-in-out infinite',
      },
      keyframes: {
        blink: {
          '0%, 100%': { opacity: '1' },
          '50%':      { opacity: '0' },
        },
        orbit: {
          from: { transform: 'rotate(0deg) translateX(14px) rotate(0deg)' },
          to:   { transform: 'rotate(360deg) translateX(14px) rotate(-360deg)' },
        },
        'radar-sweep': {
          from: { transform: 'rotate(0deg)' },
          to:   { transform: 'rotate(360deg)' },
        },
        'atb-charge': {
          '0%':   { width: '0%', opacity: '0.5' },
          '65%':  { width: '100%', opacity: '1' },
          '75%':  { width: '100%', opacity: '1' },
          '85%':  { width: '0%', opacity: '0.3' },
          '100%': { width: '0%', opacity: '0.5' },
        },
        'candle-flicker': {
          '0%, 100%': { opacity: '1', transform: 'scaleY(1)' },
          '50%':      { opacity: '0.88', transform: 'scaleY(0.97)' },
        },
      },
      boxShadow: {
        'gold-sm':    '0 0 8px 1px rgba(201,160,48,0.15)',
        'gold-md':    '0 0 20px 4px rgba(201,160,48,0.12)',
        'gold-inner': 'inset 0 1px 0 rgba(201,160,48,0.08)',
        'crystal-sm': '0 0 8px 1px rgba(74,188,170,0.15)',
        'crystal-md': '0 0 20px 4px rgba(74,188,170,0.12)',
        'parchment':  'inset 0 2px 8px rgba(0,0,0,0.4), 0 1px 0 rgba(201,160,48,0.06)',
      },
    },
  },
  plugins: [],
}

export default config
