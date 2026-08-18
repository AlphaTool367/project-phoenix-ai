import { useState } from 'react'
import { PageHeader } from '../components/Layout'
import { api, fmt, timeAgo, usePoll } from '../lib/api'

interface ReviewItem {
  id: number
  title: string
  topic: string
  status: string
  review_status: string
  review_notes: string
  scheduled_at: string | null
  hook_score?: number | null
  predicted_ctr?: number | null
  copyright_check_passed?: boolean | null
  created_at: string
}

interface ProviderUsageService {
  service: string
  requests: number
  successful_requests: number
  failed_requests: number
  prompt_tokens: number
  completion_tokens: number
  total_tokens: number
  reported_cost_usd: number | null
  cost_status: string
  models: Record<string, number>
}

interface SafetySummary {
  approval_required: boolean
  pending_review: number
  approved: number
  rejected: number
  awaiting_review: number
  failed_jobs: number
  backups: number
  notifications_enabled: boolean
  quota: {
    youtube: { configured_daily_budget_units: number; locally_tracked_units: number; remaining_local_budget_units: number; provider_balance: string }
    openrouter: { locally_tracked_units: number; provider_balance: string }
  }
  provider_usage?: {
    period_days: number
    services: ProviderUsageService[]
    provider_balances: Record<string, string>
    note: string
  }
}

interface SafetyErrors {
  jobs: { id: number; type: string; status: string; attempts: number; last_error: string | null }[]
  videos: { id: number; title: string; status: string; attempts: number; error: string | null }[]
  logs: { id: number; level: string; source: string; message: string; ts: string }[]
}

interface CalendarData {
  items: { id: number; title: string; start: string; status: string; review_status: string }[]
  recurring_slots: { id: number; hour_utc: number; minute_utc: number; length_mode: string; enabled: boolean }[]
}

interface BackupData {
  items: { name: string; size_bytes: number; modified_at: string; valid: boolean; secrets_excluded?: boolean }[]
  retention_days: number
}

export default function SafetyPage() {
  const { data: summary, error: summaryError } = usePoll<SafetySummary>('/api/safety/summary', 8000)
  const { data: reviewQueue, error: reviewError } = usePoll<ReviewItem[]>('/api/safety/review-queue', 8000)
  const { data: errors } = usePoll<SafetyErrors>('/api/safety/errors', 8000)
  const { data: calendar } = usePoll<CalendarData>('/api/safety/calendar?days=31', 15000)
  const { data: backups } = usePoll<BackupData>('/api/safety/backups', 15000)
  const [busy, setBusy] = useState<number | string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)

  const review = async (id: number, action: 'approve' | 'reject') => {
    setBusy(id)
    setNotice(null)
    try {
      await api.post(`/api/safety/review/${id}`, { action, reviewer: 'dashboard-user' })
      setNotice(action === 'approve' ? `Video #${id} approved; publishing pipeline resumed.` : `Video #${id} rejected.`)
    } catch (e) {
      setNotice(e instanceof Error ? e.message : String(e))
    } finally { setBusy(null) }
  }

  const createBackup = async () => {
    setBusy('backup')
    try {
      const result = await api.post<{ name: string }>('/api/safety/backups')
      setNotice(`Backup created: ${result.name}`)
    } catch (e) { setNotice(e instanceof Error ? e.message : String(e)) }
    finally { setBusy(null) }
  }

  const restoreBackup = async (name: string) => {
    if (!window.confirm(`Restore ${name}? The current database will be copied before restore.`)) return
    setBusy(name)
    try {
      await api.post(`/api/safety/backups/${encodeURIComponent(name)}/restore`, { confirm: true })
      setNotice(`Backup restored: ${name}. Restart Phoenix if the dashboard needs a fresh database connection.`)
    } catch (e) { setNotice(e instanceof Error ? e.message : String(e)) }
    finally { setBusy(null) }
  }

  const testNotification = async () => {
    setBusy('notification')
    try {
      await api.post('/api/safety/notifications/test')
      setNotice('Notification test recorded. It is delivered only when a webhook is configured.')
    } catch (e) { setNotice(e instanceof Error ? e.message : String(e)) }
    finally { setBusy(null) }
  }

  const quota = summary?.quota.youtube
  const quotaPct = quota ? Math.min(100, (quota.locally_tracked_units / Math.max(1, quota.configured_daily_budget_units)) * 100) : 0

  return (
    <div>
      <PageHeader title="Safety Center">
        <button className="btn-ghost" onClick={testNotification} disabled={busy === 'notification'}>test notification</button>
        <button className="btn-primary" onClick={createBackup} disabled={busy === 'backup'}>backup now</button>
      </PageHeader>

      {(summaryError || reviewError || notice) && (
        <div className="mb-5 rounded-xl border border-amber-500/30 bg-amber-500/10 px-4 py-3 text-sm text-amber-200">
          {notice || summaryError || reviewError}
        </div>
      )}

      <div className="grid grid-cols-2 gap-4 xl:grid-cols-6">
        {[
          ['Needs review', summary?.awaiting_review ?? 0, 'text-amber-300'],
          ['Pending queue', summary?.pending_review ?? 0, 'text-amber-300'],
          ['Approved', summary?.approved ?? 0, 'text-emerald-300'],
          ['Rejected', summary?.rejected ?? 0, 'text-rose-300'],
          ['Failed jobs', summary?.failed_jobs ?? 0, 'text-rose-300'],
          ['Backups', summary?.backups ?? 0, 'text-phoenix-300'],
        ].map(([label, value, tone]) => (
          <div className="card" key={String(label)}>
            <div className="text-[10px] uppercase tracking-wider text-zinc-500">{label}</div>
            <div className={`mt-2 text-2xl font-bold ${tone}`}>{value}</div>
          </div>
        ))}
      </div>

      <div className="mt-6 grid gap-6 xl:grid-cols-2">
                <section className="card">
          <div className="mb-4 flex items-center justify-between">
            <div>
              <div className="text-[10px] font-semibold uppercase tracking-[0.2em] text-fuchsia-100/55">Human approval queue</div>
              <div className="mt-1 text-xs text-white/45">{summary?.approval_required ? 'Manual mode: live uploads wait here until you approve.' : 'Automatic mode: checks run first, then clean videos can upload automatically.'}</div>
            </div>
            <span className="glass-chip text-[10px]">
              <span className={`h-1.5 w-1.5 rounded-full ${summary?.approval_required ? 'bg-amber-300' : 'bg-emerald-300'} shadow-[0_0_8px_currentColor]`} />
              {summary?.approval_required ? 'manual approval' : 'automatic safe upload'}
            </span>
          </div>

          <div className="space-y-3">
            {(reviewQueue ?? []).slice(0, 8).map((item) => (
              <div className="rounded-xl border border-white/10 bg-white/[0.035] p-3 shadow-[inset_0_1px_0_rgba(255,255,255,0.04)]" key={item.id}>
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <div className="truncate font-medium text-zinc-100">{item.title}</div>
                    <div className="mt-1 text-xs text-zinc-500">#{item.id} · {item.status} · created {timeAgo(item.created_at)}</div>
                    <div className="mt-2 flex flex-wrap gap-2 text-[10px]">
                      <span className="rounded bg-zinc-800 px-2 py-1 text-zinc-400">hook {item.hook_score ?? '—'}</span>
                      <span className="rounded bg-zinc-800 px-2 py-1 text-zinc-400">CTR {item.predicted_ctr ?? '—'}</span>
                      <span className={`rounded px-2 py-1 ${item.copyright_check_passed === false ? 'bg-rose-500/15 text-rose-300' : 'bg-zinc-800 text-zinc-400'}`}>copyright {item.copyright_check_passed == null ? 'unchecked' : item.copyright_check_passed ? 'clean' : 'flagged'}</span>
                    </div>
                  </div>
                  <div className="flex shrink-0 gap-2">
                    <button className="btn-primary !px-2 !py-1 text-xs" disabled={busy === item.id} onClick={() => review(item.id, 'approve')}>approve</button>
                    <button className="btn-ghost !px-2 !py-1 text-xs" disabled={busy === item.id} onClick={() => review(item.id, 'reject')}>reject</button>
                  </div>
                </div>
              </div>
            ))}
            {(reviewQueue ?? []).length === 0 && <div className="py-8 text-center text-sm text-zinc-600">No videos waiting for review.</div>}
          </div>
        </section>

        <section className="card">
          <div className="mb-4 flex items-center justify-between">
            <div>
              <div className="text-xs font-semibold uppercase tracking-wider text-zinc-500">Quota monitor</div>
              <div className="mt-1 text-xs text-zinc-500">Local accounting is shown separately from provider-side balances.</div>
            </div>
            <span className="rounded-full bg-amber-500/15 px-2 py-1 text-[10px] text-amber-300">provider balance unknown</span>
          </div>
          <div className="space-y-5">
            <div>
              <div className="mb-2 flex justify-between text-sm"><span className="text-zinc-300">YouTube local budget</span><span className="font-mono text-zinc-400">{quota?.locally_tracked_units ?? 0} / {quota?.configured_daily_budget_units ?? 10000} units</span></div>
              <div className="h-2 overflow-hidden rounded-full border border-white/10 bg-black/30"><div className="h-full rounded-full bg-gradient-to-r from-fuchsia-300 to-violet-400 shadow-[0_0_14px_rgba(239,159,232,0.45)]" style={{ width: `${quotaPct}%` }} /></div>
              <div className="mt-2 text-xs text-zinc-500">{quota?.provider_balance ?? 'Loading quota information…'}</div>
            </div>
            <div className="rounded-lg bg-zinc-900/70 p-3 text-xs text-zinc-400">OpenRouter balance: {summary?.quota.openrouter.provider_balance ?? 'Loading…'}</div>
            <div className="border-t border-white/8 pt-4">
              <div className="mb-2 flex items-center justify-between text-[10px] uppercase tracking-wider text-zinc-500">
                <span>Actual provider usage</span><span>last {summary?.provider_usage?.period_days ?? 1} day</span>
              </div>
              {(summary?.provider_usage?.services ?? []).map((item) => (
                <div className="mb-2 rounded-lg border border-white/8 bg-black/15 p-3 text-xs" key={item.service}>
                  <div className="flex items-center justify-between"><span className="font-medium text-zinc-200">{item.service}</span><span className="text-zinc-500">{item.requests} requests · {item.total_tokens} tokens</span></div>
                  <div className="mt-1 flex items-center justify-between text-zinc-500"><span>success {item.successful_requests} · failed {item.failed_requests}</span><span>{item.reported_cost_usd == null ? 'cost unknown' : `$${item.reported_cost_usd.toFixed(6)} reported`}</span></div>
                </div>
              ))}
              {(summary?.provider_usage?.services ?? []).length === 0 && <div className="rounded-lg bg-zinc-900/70 p-3 text-xs text-zinc-500">No provider response usage recorded yet. Costs remain unknown until a provider reports them.</div>}
              <div className="mt-2 text-[10px] leading-relaxed text-zinc-600">{summary?.provider_usage?.note ?? 'No estimated prices or fake balances are shown.'}</div>
            </div>
          </div>
        </section>
      </div>

      <div className="mt-6 grid gap-6 xl:grid-cols-2">
        <section className="card">
          <div className="mb-4 text-xs font-semibold uppercase tracking-wider text-zinc-500">Content calendar</div>
          <div className="space-y-2">
            {(calendar?.items ?? []).map((item) => (
              <div className="flex items-center justify-between rounded-lg border border-ink-600 px-3 py-2" key={item.id}>
                <div><div className="text-sm text-zinc-200">{item.title}</div><div className="text-[11px] text-zinc-500">{new Date(item.start).toLocaleString()}</div></div>
                <span className="text-[10px] text-zinc-400">{item.status} · {item.review_status}</span>
              </div>
            ))}
            {(calendar?.items ?? []).length === 0 && <div className="py-5 text-center text-sm text-zinc-600">No scheduled videos in the next 31 days.</div>}
          </div>
          <div className="mt-4 border-t border-ink-700 pt-3 text-xs text-zinc-500">Recurring slots: {calendar?.recurring_slots.length ?? 0}</div>
        </section>

        <section className="card">
          <div className="mb-4 flex items-center justify-between"><div className="text-xs font-semibold uppercase tracking-wider text-zinc-500">Error center</div><span className="text-xs text-zinc-500">failed jobs, videos, warnings</span></div>
          <div className="max-h-64 space-y-2 overflow-auto">
                        {(errors?.jobs ?? []).slice(0, 6).map((job) => <div className="rounded-xl border border-rose-200/15 bg-rose-300/[0.07] px-3 py-2 text-xs" key={`job-${job.id}`}>
<span className="text-rose-300">Job #{job.id} · {job.status}</span><div className="mt-1 text-zinc-400">{job.last_error || job.type}</div></div>)}
                        {(errors?.videos ?? []).slice(0, 6).map((video) => <div className="rounded-xl border border-rose-200/15 bg-rose-300/[0.07] px-3 py-2 text-xs" key={`video-${video.id}`}>
<span className="text-rose-300">Video #{video.id} · {video.title}</span><div className="mt-1 text-zinc-400">{video.error || 'video failed without a message'}</div></div>)}
            {(errors?.jobs ?? []).length === 0 && (errors?.videos ?? []).length === 0 && <div className="py-5 text-center text-sm text-zinc-600">No failed jobs or videos.</div>}
          </div>
        </section>
      </div>

      <section className="card mt-6">
        <div className="mb-4 flex items-center justify-between"><div className="text-xs font-semibold uppercase tracking-wider text-zinc-500">Safe backups</div><span className="text-xs text-zinc-500">retention: {backups?.retention_days ?? 14} days · secrets excluded</span></div>
        <div className="space-y-2">
          {(backups?.items ?? []).slice(0, 6).map((backup) => <div className="flex items-center justify-between gap-3 rounded-lg border border-ink-600 px-3 py-2 text-sm" key={backup.name}><span className="min-w-0 truncate text-zinc-300">{backup.name}</span><div className="flex items-center gap-2"><span className="text-xs text-zinc-500">{Math.round(backup.size_bytes / 1024)} KB · {backup.valid ? 'valid' : 'invalid'}</span><button className="btn-ghost !px-2 !py-1 text-xs" disabled={!backup.valid || busy === backup.name} onClick={() => restoreBackup(backup.name)}>restore</button></div></div>)}
          {(backups?.items ?? []).length === 0 && <div className="py-5 text-center text-sm text-zinc-600">No backups yet. Click “backup now”.</div>}
        </div>
      </section>
    </div>
  )
}
