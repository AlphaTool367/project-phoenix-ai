import { useState } from 'react'
import { PageHeader } from '../components/Layout'
import StatusBadge from '../components/StatusBadge'
import { api, timeAgo, usePoll } from '../lib/api'
import type { Channel, Job, ScheduledSlot, SettingsView } from '../lib/types'

const NICHES = ['technology', 'finance', 'health', 'space', 'history', 'science',
  'education', 'entertainment', 'gaming', 'lifestyle', 'news', 'music',
  'travel', 'food', 'fitness', 'sports', 'automotive', 'diy', 'art',
  'business', 'psychology', 'philosophy', 'politics', 'fashion']
const LENGTH_MODES = [
  { value: 'manual', label: 'Manual' },
  { value: 'shorts', label: 'Shorts (30s–3min)' },
  { value: 'long', label: 'Long (3–10min)' },
]

interface SchedJob {
  id: string
  next_run: string | null
  trigger: string
}

interface SchedulerSettings {
  auto_trigger: boolean
  copyright_check_enabled: boolean
  copyright_wait_seconds: number
  auto_publish_after_check: boolean
  post_check_privacy: string
}

function NewSlotForm({ channels, onCreated }: {
  channels: Channel[]
  onCreated: () => void
}) {
  const { data: settings } = usePoll<SettingsView>('/api/settings', 30000)
  const [open, setOpen] = useState(false)
  const [channelId, setChannelId] = useState<number>(channels[0]?.id ?? 1)
  const [hour, setHour] = useState<number>(13)
  const [minute, setMinute] = useState<number>(0)
  const [lengthMode, setLengthMode] = useState<string>('manual')
  const [targetSeconds, setTargetSeconds] = useState<number>(150)
  const [categories, setCategories] = useState<string[]>(['technology'])
  const [language, setLanguage] = useState<string>('')
  const [busy, setBusy] = useState(false)

  const toggleCat = (c: string) => {
    setCategories((cur) => cur.includes(c) ? cur.filter((x) => x !== c) : [...cur, c])
  }

  const create = async () => {
    setBusy(true)
    try {
      await api.post('/api/scheduler/slots', {
        channel_id: channelId,
        hour, minute,
        categories,
        length_mode: lengthMode,
        target_seconds: lengthMode === 'manual' ? targetSeconds : null,
        language: language || null,
        enabled: true,
      })
      setOpen(false)
      onCreated()
    } finally {
      setBusy(false)
    }
  }

  if (!open) {
    return <button className="btn-primary" onClick={() => setOpen(true)}>＋ New slot</button>
  }

  return (
    <div className="card mb-6">
      <div className="mb-3 text-xs font-semibold uppercase tracking-wider text-zinc-500">
        New scheduled slot
      </div>
      <div className="grid gap-3 md:grid-cols-4">
        <div>
          <label className="label">Channel</label>
          <select className="input" value={channelId}
            onChange={(e) => setChannelId(Number(e.target.value))}>
            {channels.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
          </select>
        </div>
        <div>
          <label className="label">Hour (UTC)</label>
          <select className="input" value={hour} onChange={(e) => setHour(Number(e.target.value))}>
            {Array.from({ length: 24 }, (_, i) => <option key={i} value={i}>{i}:00</option>)}
          </select>
        </div>
        <div>
          <label className="label">Minute</label>
          <select className="input" value={minute} onChange={(e) => setMinute(Number(e.target.value))}>
            {[0, 15, 30, 45].map((m) => <option key={m} value={m}>:{m.toString().padStart(2, '0')}</option>)}
          </select>
        </div>
        <div>
          <label className="label">Length mode</label>
          <select className="input" value={lengthMode} onChange={(e) => setLengthMode(e.target.value)}>
            {LENGTH_MODES.map((m) => <option key={m.value} value={m.value}>{m.label}</option>)}
          </select>
        </div>
      </div>

      {lengthMode === 'manual' && (
        <div className="mt-3">
          <label className="label">Target seconds</label>
          <input className="input" type="number" min={15} max={3600}
            value={targetSeconds}
            onChange={(e) => setTargetSeconds(Number(e.target.value))} />
        </div>
      )}

      <div className="mt-3">
        <label className="label">Language override (optional)</label>
        <select className="input" value={language} onChange={(e) => setLanguage(e.target.value)}>
          <option value="">— use channel default —</option>
          {(settings?.options.languages ?? []).map((l) =>
            <option key={l.code} value={l.code}>{l.label}</option>)}
        </select>
      </div>

      <div className="mt-3">
        <label className="label">Categories (per-slot niche filter)</label>
        <div className="flex flex-wrap gap-1.5">
          {NICHES.map((n) => (
            <button key={n} type="button" onClick={() => toggleCat(n)}
              className={`rounded-full px-3 py-1 text-xs font-semibold transition-colors ${
                categories.includes(n)
                  ? 'bg-phoenix-500/30 text-phoenix-200 ring-1 ring-phoenix-400'
                  : 'bg-ink-700 text-zinc-400 hover:bg-ink-600 hover:text-zinc-200'
              }`}>
              {n}
            </button>
          ))}
        </div>
      </div>

      <div className="mt-4 flex gap-2">
        <button className="btn-primary" onClick={create} disabled={busy}>
          {busy ? 'creating…' : 'Create slot'}
        </button>
        <button className="btn-ghost" onClick={() => setOpen(false)}>Cancel</button>
      </div>
    </div>
  )
}

function SlotCard({ slot, onChanged }: { slot: ScheduledSlot; onChanged: () => void }) {
  const [firing, setFiring] = useState(false)
  const [msg, setMsg] = useState('')

  const fire = async () => {
    setFiring(true)
    setMsg('')
    try {
      await api.post(`/api/scheduler/slots/${slot.id}/fire`)
      setMsg('✓ fired — check Videos page for progress')
      onChanged()
    } catch (e) {
      setMsg(`✗ ${e instanceof Error ? e.message : String(e)}`)
    } finally {
      setFiring(false)
    }
  }

  const toggle = async () => {
    await api.post(`/api/scheduler/slots/${slot.id}/toggle`)
    onChanged()
  }

  const remove = async () => {
    if (!confirm('Delete this scheduled slot?')) return
    await api.delete(`/api/scheduler/slots/${slot.id}`)
    onChanged()
  }

  return (
    <div className={`rounded-xl border p-4 ${slot.enabled ? 'border-phoenix-500/30 bg-ink-800' : 'border-ink-600 bg-ink-900'}`}>
      <div className="flex items-start justify-between">
        <div>
          <div className="font-mono text-lg font-bold text-white">
            {slot.hour.toString().padStart(2, '0')}:{slot.minute.toString().padStart(2, '0')}
            <span className="ml-2 text-xs font-normal text-zinc-500">UTC</span>
          </div>
          <div className="mt-1 text-xs text-zinc-400">
            mode: <span className="text-phoenix-300">{slot.length_mode}</span>
            {slot.target_seconds && ` · ${slot.target_seconds}s`}
            {slot.language && ` · ${slot.language}`}
          </div>
          {slot.categories.length > 0 && (
            <div className="mt-2 flex flex-wrap gap-1">
              {slot.categories.map((c) => (
                <span key={c} className="rounded bg-ink-700 px-1.5 py-0.5 text-[10px] text-zinc-300">
                  {c}
                </span>
              ))}
            </div>
          )}
          {slot.last_fired_at && (
            <div className="mt-2 text-[10px] text-zinc-500">
              last fired: {timeAgo(slot.last_fired_at)}
              {slot.last_video_id && ` · video #${slot.last_video_id}`}
            </div>
          )}
        </div>
        <StatusBadge status={slot.enabled ? 'published' : 'cancelled'} />
      </div>

      {msg && (
        <div className="mt-3 rounded-lg bg-ink-900 px-3 py-2 text-[11px] text-zinc-300">
          {msg}
        </div>
      )}

      <div className="mt-3 flex flex-wrap gap-2">
        <button
          className="btn-primary !px-3 !py-1 text-xs"
          onClick={fire}
          disabled={firing}
          title="Trigger this slot now — produces one video with the slot's settings"
        >
          {firing ? 'firing…' : '▶ Fire now'}
        </button>
        <button className="btn-ghost !px-3 !py-1 text-xs" onClick={toggle}>
          {slot.enabled ? '⏸ disable' : '▶ enable'}
        </button>
        <button className="btn-ghost !px-3 !py-1 text-xs" onClick={remove}>
          ✕ delete
        </button>
      </div>
    </div>
  )
}

export default function SchedulerPage() {
  const { data: channels } = usePoll<Channel[]>('/api/channels', 10000)
  const { data: schedJobs } = usePoll<SchedJob[]>('/api/jobs/scheduler', 8000)
  const { data: jobs } = usePoll<Job[]>('/api/jobs?limit=50', 5000)
  const { data: slots } = usePoll<ScheduledSlot[]>('/api/scheduler/slots', 5000)
  const { data: schedSettings } = usePoll<SchedulerSettings>('/api/scheduler/settings', 15000)
  const [tick, setTick] = useState(0)

  const retry = async (id: number) => { await api.post(`/api/jobs/${id}/retry`) }
  const control = async (action: 'start' | 'pause' | 'resume') => {
    await api.post(`/api/jobs/scheduler/${action}`)
  }

  return (
    <div>
      <PageHeader title="Automation & Scheduler">
        <button className="btn-ghost" onClick={() => control('pause')}>⏸ pause</button>
        <button className="btn-primary" onClick={() => control('resume')}>▶ resume</button>
      </PageHeader>

      {/* Scheduler settings summary */}
      {schedSettings && (
        <div className="card mb-6">
          <div className="mb-3 text-xs font-semibold uppercase tracking-wider text-zinc-500">
            Scheduler behavior
          </div>
          <div className="grid grid-cols-2 gap-3 text-sm md:grid-cols-5">
            <div className="rounded-lg bg-ink-800 px-3 py-2">
              <div className="text-[10px] uppercase text-zinc-500">Auto-trigger</div>
              <div className={schedSettings.auto_trigger ? 'text-emerald-400' : 'text-amber-400'}>
                {schedSettings.auto_trigger ? 'ON' : 'OFF'}
              </div>
            </div>
            <div className="rounded-lg bg-ink-800 px-3 py-2">
              <div className="text-[10px] uppercase text-zinc-500">Copyright check</div>
              <div className={schedSettings.copyright_check_enabled ? 'text-emerald-400' : 'text-amber-400'}>
                {schedSettings.copyright_check_enabled ? 'ON' : 'OFF'}
              </div>
            </div>
            <div className="rounded-lg bg-ink-800 px-3 py-2">
              <div className="text-[10px] uppercase text-zinc-500">Wait before check</div>
              <div className="text-zinc-200">{schedSettings.copyright_wait_seconds}s</div>
            </div>
            <div className="rounded-lg bg-ink-800 px-3 py-2">
              <div className="text-[10px] uppercase text-zinc-500">Auto-publish</div>
              <div className={schedSettings.auto_publish_after_check ? 'text-emerald-400' : 'text-amber-400'}>
                {schedSettings.auto_publish_after_check ? 'ON' : 'OFF'}
              </div>
            </div>
            <div className="rounded-lg bg-ink-800 px-3 py-2">
              <div className="text-[10px] uppercase text-zinc-500">Post-check privacy</div>
              <div className="text-zinc-200">{schedSettings.post_check_privacy}</div>
            </div>
          </div>
          <div className="mt-3 text-[11px] text-zinc-500">
            Upload flow: <code className="rounded bg-ink-900 px-1">unlisted</code> →{' '}
            wait {schedSettings.copyright_wait_seconds}s →{' '}
            check claims →{' '}
            <code className="rounded bg-ink-900 px-1">{schedSettings.copyright_check_enabled ? 'delete if claimed' : 'skip check'}</code> →{' '}
            <code className="rounded bg-ink-900 px-1">{schedSettings.auto_publish_after_check ? `publish as ${schedSettings.post_check_privacy}` : 'leave unlisted'}</code>
          </div>
        </div>
      )}

      {/* Scheduled slots */}
      <div className="mb-6">
        {channels && channels.length > 0 && (
          <NewSlotForm channels={channels} onCreated={() => setTick((t) => t + 1)} />
        )}
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          {(slots ?? []).map((s) => (
            <SlotCard key={`${s.id}-${tick}`} slot={s} onChanged={() => setTick((t) => t + 1)} />
          ))}
        </div>
        {(slots ?? []).length === 0 && (
          <div className="card py-12 text-center text-sm text-zinc-600">
            No scheduled slots yet — create one above to auto-produce a video at a set time each day.
            <div className="mt-2 text-[11px]">
              Each slot fires automatically when its time arrives (if auto-trigger is ON).
              You can also fire any slot manually with the "Fire now" button.
            </div>
          </div>
        )}
      </div>

      {/* Recurring automation jobs */}
      <div className="card mb-6">
        <div className="mb-4 text-xs font-semibold uppercase tracking-wider text-zinc-500">
          Recurring automation (persisted — survives restarts)
        </div>
        <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
          {(schedJobs ?? []).map((j) => (
            <div key={j.id} className="rounded-xl bg-ink-800 p-4">
              <div className="font-mono text-sm font-semibold text-phoenix-300">{j.id}</div>
              <div className="mt-1 text-xs text-zinc-500">{j.trigger}</div>
              <div className="mt-2 text-xs text-zinc-400">
                next run: {j.next_run ? new Date(j.next_run).toLocaleString() : '—'}
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* Durable job queue */}
      <div className="card">
        <div className="mb-4 text-xs font-semibold uppercase tracking-wider text-zinc-500">
          Job queue (durable, auto-retry)
        </div>
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-xs uppercase tracking-wider text-zinc-500">
              <th className="pb-2">#</th>
              <th className="pb-2">Type</th>
              <th className="pb-2">Status</th>
              <th className="pb-2">Attempts</th>
              <th className="pb-2">Run at</th>
              <th className="pb-2">Error</th>
              <th className="pb-2"></th>
            </tr>
          </thead>
          <tbody className="divide-y divide-ink-700">
            {(jobs ?? []).map((j) => (
              <tr key={j.id}>
                <td className="py-2.5 font-mono text-zinc-500">{j.id}</td>
                <td className="py-2.5 text-zinc-200">{j.type}</td>
                <td className="py-2.5"><StatusBadge status={j.status} /></td>
                <td className="py-2.5 font-mono text-zinc-400">{j.attempts}/{j.max_attempts}</td>
                <td className="py-2.5 text-xs text-zinc-500">{timeAgo(j.run_at)}</td>
                <td className="max-w-xs truncate py-2.5 text-xs text-rose-400">{j.last_error ?? ''}</td>
                <td className="py-2.5 text-right">
                  {['failed', 'dead'].includes(j.status) && (
                    <button className="btn-ghost !px-2 !py-0.5 text-xs" onClick={() => retry(j.id)}>
                      ↻ retry
                    </button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {(jobs ?? []).length === 0 && (
          <div className="py-6 text-center text-xs text-zinc-600">queue is empty</div>
        )}
      </div>
    </div>
  )
}
