import { useEffect, useRef } from 'react'
import type { LogEntry } from '../lib/types'

const LEVEL_COLOR: Record<string, string> = {
  INFO: 'text-sky-400',
  WARNING: 'text-amber-400',
  ERROR: 'text-rose-400',
  CRITICAL: 'text-rose-500',
  DEBUG: 'text-zinc-500',
}

export default function LogConsole({
  entries,
  connected,
  height = 'h-96',
}: {
  entries: LogEntry[]
  connected?: boolean
  height?: string
}) {
  const boxRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const el = boxRef.current
    if (el) el.scrollTop = el.scrollHeight
  }, [entries])

  return (
    <div className="card !p-0 overflow-hidden">
      <div className="flex items-center justify-between border-b border-ink-600 px-4 py-2.5">
        <div className="text-xs font-semibold uppercase tracking-wider text-zinc-500">
          AI Activity Stream
        </div>
        {connected !== undefined && (
          <div className="flex items-center gap-1.5 text-[11px] text-zinc-500">
            <span className={`h-2 w-2 rounded-full ${connected ? 'bg-emerald-400' : 'bg-rose-400'}`} />
            {connected ? 'live' : 'disconnected'}
          </div>
        )}
      </div>
      <div ref={boxRef} className={`${height} overflow-y-auto px-4 py-3 font-mono text-xs leading-relaxed`}>
        {entries.length === 0 && (
          <div className="text-zinc-600">waiting for AI activity…</div>
        )}
        {entries.map((e, i) => (
          <div key={i} className="flex gap-3 py-0.5">
            <span className="shrink-0 text-zinc-600">
              {new Date(e.ts).toLocaleTimeString()}
            </span>
            <span className={`shrink-0 w-14 font-bold ${LEVEL_COLOR[e.level] ?? 'text-zinc-400'}`}>
              {e.level}
            </span>
            <span className="shrink-0 w-24 truncate text-phoenix-400/80">{e.source}</span>
            <span className="text-zinc-300">{e.message}</span>
          </div>
        ))}
      </div>
    </div>
  )
}
