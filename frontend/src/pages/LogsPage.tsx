import { useState } from 'react'
import { PageHeader } from '../components/Layout'
import LogConsole from '../components/LogConsole'
import { useLogStream, usePoll } from '../lib/api'
import type { LogEntry } from '../lib/types'

export default function LogsPage() {
  const { entries, connected } = useLogStream(500)
  const [level, setLevel] = useState('')
  const { data: history } = usePoll<LogEntry[]>(
    `/api/dashboard/logs?limit=200${level ? `&level=${level}` : ''}`, 10000,
  )

  // live stream first, history fallback for initial paint
  const shown = entries.length > 0 ? entries : [...(history ?? [])].reverse()

  return (
    <div>
      <PageHeader title="AI Activity Logs">
        {['', 'INFO', 'WARNING', 'ERROR'].map((l) => (
          <button key={l} onClick={() => setLevel(l)}
            className={`rounded-full px-3 py-1 text-xs font-semibold transition-colors ${
              level === l ? 'bg-phoenix-500/20 text-phoenix-300' : 'bg-ink-700 text-zinc-400'
            }`}>
            {l || 'all'}
          </button>
        ))}
      </PageHeader>
      <LogConsole entries={shown} connected={connected} height="h-[70vh]" />
    </div>
  )
}
