import type { Metadata } from 'next'
import './globals.css'

export const metadata: Metadata = {
  title: 'Crystal Swarm IDE — Final Chronicles',
  description: 'Multi-agent spellcasting IDE — FFIX Edition',
}

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="es" className="h-full">
      <head>
        <link rel="preconnect" href="https://fonts.googleapis.com" />
        <link rel="preconnect" href="https://fonts.gstatic.com" crossOrigin="anonymous" />
        <link
          href="https://fonts.googleapis.com/css2?family=Cinzel:wght@400;500;600;700&family=Crimson+Text:ital,wght@0,400;0,600;1,400&family=JetBrains+Mono:ital,wght@0,300;0,400;0,500;0,600;1,400&display=swap"
          rel="stylesheet"
        />
      </head>
      <body className="h-full overflow-hidden font-crimson" style={{ background: '#080c1a', color: '#e0c878' }}>
        {children}
      </body>
    </html>
  )
}
