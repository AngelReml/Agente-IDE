import type { Metadata } from 'next'
import './globals.css'

export const metadata: Metadata = {
  title: 'Swarm IDE',
  description: 'Multi-agent developer swarm — Cyberpunk Liquid Edition',
}

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="es" className="h-full">
      <head>
        <link rel="preconnect" href="https://fonts.googleapis.com" />
        <link rel="preconnect" href="https://fonts.gstatic.com" crossOrigin="anonymous" />
        <link
          href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&family=JetBrains+Mono:ital,wght@0,300;0,400;0,500;0,600;1,400&display=swap"
          rel="stylesheet"
        />
      </head>
      <body className="h-full overflow-hidden bg-[#050609] text-[#d4d8e8] font-sans">
        {children}
      </body>
    </html>
  )
}
