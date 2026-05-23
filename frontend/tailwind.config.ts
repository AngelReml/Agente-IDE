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
        sans: ['Inter', 'Geist', 'system-ui', 'sans-serif'],
        mono: ['JetBrains Mono', 'Fira Code', 'Cascadia Code', 'Consolas', 'monospace'],
      },
      colors: {
        bg: '#050609',
        surface: {
          DEFAULT: '#08090d',
          1: '#0d0f14',
          2: '#121419',
          3: '#181b22',
        },
        border: {
          DEFAULT: '#1a1c22',
          2: '#242730',
        },
        cyan: {
          DEFAULT: '#00f0ff',
          dim: 'rgba(0,240,255,0.10)',
          mid: 'rgba(0,240,255,0.15)',
          bright: 'rgba(0,240,255,0.30)',
        },
        magenta: {
          DEFAULT: '#ff0055',
          dim: 'rgba(255,0,85,0.10)',
          mid: 'rgba(255,0,85,0.15)',
        },
        accent: {
          DEFAULT: '#7c3aed',
          hover: '#6d28d9',
          soft: '#4c1d95',
        },
      },
      animation: {
        'pulse-slow':   'pulse 3s cubic-bezier(0.4, 0, 0.6, 1) infinite',
        'pulse-slower': 'pulse 4s cubic-bezier(0.4, 0, 0.6, 1) infinite',
        'blink':        'blink 1s step-end infinite',
        'orbit':        'orbit 8s linear infinite',
        'radar':        'radar-sweep 2s linear infinite',
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
      },
      backdropBlur: {
        xs: '2px',
      },
      boxShadow: {
        'cyan-sm': '0 0 8px 1px rgba(0,240,255,0.12)',
        'cyan-md': '0 0 20px 4px rgba(0,240,255,0.10)',
        'magenta-sm': '0 0 8px 1px rgba(255,0,85,0.12)',
        'magenta-md': '0 0 20px 4px rgba(255,0,85,0.10)',
      },
    },
  },
  plugins: [],
}

export default config
