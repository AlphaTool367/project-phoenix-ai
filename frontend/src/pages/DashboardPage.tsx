import { Link } from 'react-router-dom'
import HealthPanel from '../components/HealthPanel'
import LogConsole from '../components/LogConsole'
import ProgressBar from '../components/ProgressBar'
import StatCard from '../components/StatCard'
import StatusBadge from '../components/StatusBadge'
import { fmt, timeAgo, useLogStream, usePoll } from '../lib/api'
import type { AnalyticsSummary, Channel, DashboardSummary, Video } from '../lib/types'
import { PageHeader } from '../components/Layout'

export default function DashboardPage() {
  const { data: summary } = usePoll<DashboardSummary>('/api/dashboard/summary', 4000)
  const { data: videos } = usePoll<Video[]>('/api/videos?limit=6', 4000)
  const { data: channels } = usePoll<Channel[]>('/api/channels', 8000)
  const firstChannel = channels?.[0]?.id
  const { data: analytics } = usePoll<AnalyticsSummary>(
    firstChannel ? `/api/analytics/channel/${firstChannel}` : '/api/analytics/channel/0',
    8000,
  )
  const { entries, connected } = useLogStream()

  if (!summary) return <div className="text-zinc-500">connecting to Phoenix…</div>

  const active = Object.entries(summary.rendering_now)

  return (
    <div>
      <PageHeader title="Mission Control">
        <Link to="/videos" className="btn-primary">＋ New Video</Link>
      </PageHeader>

      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        <StatCard label="Channels" value={summary.channels} icon="☰" />
        <StatCard label="Videos produced" value={summary.videos_total} icon="▶"
          sub={`${summary.videos_by_status['published'] ?? 0} published`} />
        <StatCard label="Jobs queued" value={summary.queue.queued} icon="◷"
          sub={`${summary.queue.dead} need attention`} />
        <StatCard label="Total views" value={
          <span className="text-phoenix-400">{fmt(analytics?.views ?? 0)}</span>
        } icon="↗" sub={analytics ? `${fmt(analytics.subs_gained)} subs gained` : 'no data yet'} />
      </div>

      {active.length > 0 && (
        <div className="card mt-6">
          <div className="mb-4 text-xs font-semibold uppercase tracking-wider text-zinc-500">
            Rendering now
          </div>
          <div className="space-y-4">
            {active.map(([vid, p]) => (
              <ProgressBar key={vid} pct={p.pct} label={`video #${vid} — ${p.stage}`} />
            ))}
          </div>
        </div>
      )}

      <div className="mt-6 grid gap-6 lg:grid-cols-3">
        <div className="lg:col-span-2 space-y-6">
          <div className="card">
            <div className="mb-4 flex items-center justify-between">
              <div className="text-xs font-semibold uppercase tracking-wider text-zinc-500">
                Latest videos
              </div>
              <Link to="/videos" className="text-xs text-phoenix-400 hover:text-phoenix-300">
                view all →
              </Link>
            </div>
            <div className="divide-y divide-ink-700">
              {(videos ?? []).map((v) => (
                <div key={v.id} className="flex items-center justify-between gap-3 py-2.5">
                  <div className="min-w-0">
                    <div className="truncate text-sm font-medium text-zinc-200">
                      {v.title || v.topic}
                    </div>
                    <div className="text-xs text-zinc-500">
                      #{v.id} · {v.niche} · {timeAgo(v.created_at)}
                    </div>
                  </div>
                  <StatusBadge status={v.status} />
                </div>
              ))}
              {(videos ?? []).length === 0 && (
                <div className="py-6 text-center text-sm text-zinc-600">
                  no videos yet — the AI starts at 06:00, or trigger one manually
                </div>
              )}
            </div>
          </div>
          <LogConsole entries={entries} connected={connected} height="h-72" />
        </div>
        <div className="space-y-6">
          <HealthPanel summary={summary} />
          <div className="card">
            <div className="mb-3 text-xs font-semibold uppercase tracking-wider text-zinc-500">
              Scheduler
            </div>
            <div className="space-y-2 text-sm">
              {summary.scheduler.map((j) => (
                <div key={j.id} className="flex items-center justify-between">
                  <span className="text-zinc-300">{j.id}</span>
                  <span className="text-xs text-zinc-500">
                    {j.next_run ? new Date(j.next_run).toLocaleString() : '—'}
                  </span>
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
