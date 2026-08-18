import { useState } from 'react'
import { Link } from 'react-router-dom'
import { PageHeader } from '../components/Layout'
import StatusBadge from '../components/StatusBadge'
import { api, fmt, usePoll } from '../lib/api'
import type { Channel, OAuthStartResponse, OAuthStatus, StrategyProfile } from '../lib/types'

const NICHES = ['technology', 'finance', 'health', 'space', 'history', 'science',
  'education', 'entertainment', 'gaming', 'lifestyle', 'news', 'music']
const LANGUAGES = [
  { code: 'en', label: 'English' },
  { code: 'ur', label: 'Urdu / اردو' },
  { code: 'hi', label: 'Hindi / हिंदी' },
  { code: 'es', label: 'Spanish / Español' },
  { code: 'ar', label: 'Arabic / العربية' },
  { code: 'de', label: 'German / Deutsch' },
  { code: 'fr', label: 'French / Français' },
  { code: 'pt', label: 'Portuguese / Português' },
  { code: 'tr', label: 'Turkish / Türkçe' },
]

function NewChannelForm({ onCreated }: { onCreated: () => void }) {
  const [open, setOpen] = useState(false)
  const [form, setForm] = useState({ name: '', niche: 'technology', language: 'en', videos_per_day: 3 })
  const [busy, setBusy] = useState(false)

  const create = async () => {
    if (!form.name.trim()) return
    setBusy(true)
    try {
      await api.post('/api/channels', form)
      setOpen(false)
      setForm({ name: '', niche: 'technology', language: 'en', videos_per_day: 3 })
      onCreated()
    } finally {
      setBusy(false)
    }
  }

  if (!open) return <button className="btn-primary" onClick={() => setOpen(true)}>＋ Add channel</button>

  return (
    <div className="card mb-6">
      <div className="mb-3 text-xs font-semibold uppercase tracking-wider text-zinc-500">New channel</div>
      <div className="flex flex-wrap items-end gap-3">
        <div className="min-w-52 flex-1">
          <label className="label">Name</label>
          <input className="input" value={form.name}
            onChange={(e) => setForm({ ...form, name: e.target.value })} placeholder="Cosmos Daily" />
        </div>
        <div className="w-44">
          <label className="label">Niche</label>
          <select className="input" value={form.niche}
            onChange={(e) => setForm({ ...form, niche: e.target.value })}>
            {NICHES.map((n) => <option key={n}>{n}</option>)}
          </select>
        </div>
        <div className="w-40">
          <label className="label">Language</label>
          <select className="input" value={form.language}
            onChange={(e) => setForm({ ...form, language: e.target.value })}>
            {LANGUAGES.map((l) => <option key={l.code} value={l.code}>{l.label}</option>)}
          </select>
        </div>
        <div className="w-36">
          <label className="label">Videos / day</label>
          <input className="input" type="number" min={1} max={10} value={form.videos_per_day}
            onChange={(e) => setForm({ ...form, videos_per_day: Number(e.target.value) })} />
        </div>
        <div className="flex gap-2">
          <button className="btn-primary" onClick={create} disabled={busy}>
            {busy ? 'creating…' : 'Create'}
          </button>
          <button className="btn-ghost" onClick={() => setOpen(false)}>Cancel</button>
        </div>
      </div>
    </div>
  )
}

function YouTubeConnect({ channel, onChanged }: { channel: Channel; onChanged: () => void }) {
  const { data: status } = usePoll<OAuthStatus>(`/api/channels/${channel.id}/oauth/status`, 8000)
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState('')

  const start = async () => {
    setBusy(true)
    setMsg('')
    try {
      // Detect credential type — Desktop app uses CLI auth, Web app uses web OAuth
      const st = await api.get<OAuthStatus & { credential_type?: string }>(
        `/api/channels/${channel.id}/oauth/status`)
      if (st.credential_type === 'desktop') {
        // Desktop app credential — use CLI auth (no redirect URI needed).
        await api.post(`/api/channels/${channel.id}/oauth/cli`)
        setMsg('CLI auth started — your browser should open. Complete Google consent.')
        const start = Date.now()
        const poll = window.setInterval(async () => {
          try {
            const s = await api.get<OAuthStatus>(`/api/channels/${channel.id}/oauth/status`)
            if (s.connected) {
              window.clearInterval(poll)
              setMsg('✓ YouTube connected!')
              setBusy(false)
              onChanged()
            } else if (Date.now() - start > 5 * 60 * 1000) {
              window.clearInterval(poll)
              setMsg('Timed out waiting for consent. Try again.')
              setBusy(false)
            }
          } catch {
            /* keep polling */
          }
        }, 3000)
      } else {
        // Web app credential — use web OAuth (popup).
        const r = await api.post<OAuthStartResponse>(`/api/channels/${channel.id}/oauth/start`)
        const w = window.open(r.auth_url, 'yt-oauth', 'width=600,height=700')
        if (!w) {
          window.location.href = r.auth_url
        }
        setMsg('Popup opened — complete Google consent, then come back here.')
        const start = Date.now()
        const poll = window.setInterval(async () => {
          try {
            const s = await api.get<OAuthStatus>(`/api/channels/${channel.id}/oauth/status`)
            if (s.connected) {
              window.clearInterval(poll)
              setMsg('✓ YouTube connected!')
              setBusy(false)
              onChanged()
            } else if (Date.now() - start > 5 * 60 * 1000) {
              window.clearInterval(poll)
              setMsg('Timed out waiting for consent. Try again.')
              setBusy(false)
            }
          } catch {
            /* keep polling */
          }
        }, 3000)
      }
    } catch (e) {
      setMsg(`✗ ${e instanceof Error ? e.message : String(e)}`)
      setBusy(false)
    }
  }

  const refresh = async () => {
    setBusy(true)
    setMsg('')
    try {
      await api.post(`/api/channels/${channel.id}/oauth/refresh`)
      setMsg('✓ Stats refreshed')
      onChanged()
    } catch (e) {
      setMsg(`✗ ${e instanceof Error ? e.message : String(e)}`)
    } finally {
      setBusy(false)
    }
  }

  if (!status) return null

  return (
    <div className="mt-4 rounded-xl border border-ink-700 bg-ink-800 p-3">
      <div className="mb-2 flex items-center justify-between">
        <div className="text-[11px] font-semibold uppercase tracking-wider text-phoenix-400">
          📺 YouTube connection
        </div>
        <span className={`rounded-full px-2 py-0.5 text-[10px] font-semibold ${
          status.connected
            ? 'bg-emerald-500/20 text-emerald-300'
            : 'bg-zinc-700 text-zinc-400'
        }`}>
          {status.connected ? '● CONNECTED' : '○ not connected'}
        </span>
      </div>

      {status.connected ? (
        <div>
          {status.needs_reauth && (
            <div className="mb-3 rounded-lg bg-amber-500/15 px-3 py-2 text-[11px] text-amber-300">
              ⚠ Re-authentication needed — new permissions (force-ssl scope) were added.
              Click "Re-connect YouTube" below to update your token.
            </div>
          )}
          <div className="grid grid-cols-3 gap-2 text-center text-xs">
            <div>
              <div className="text-zinc-500">Subscribers</div>
              <div className="font-semibold text-zinc-200">
                {status.yt_subscriber_count != null ? fmt(status.yt_subscriber_count) : '—'}
              </div>
            </div>
            <div>
              <div className="text-zinc-500">Videos</div>
              <div className="font-semibold text-zinc-200">
                {status.yt_video_count != null ? fmt(status.yt_video_count) : '—'}
              </div>
            </div>
            <div>
              <div className="text-zinc-500">Total views</div>
              <div className="font-semibold text-zinc-200">
                {status.yt_view_count != null ? fmt(status.yt_view_count) : '—'}
              </div>
            </div>
          </div>
        </div>
      ) : (
        <div className="text-[11px] text-zinc-400">
          Connect your YouTube channel to enable auto-upload + live analytics.
          {!status.has_secrets && (
            <div className="mt-1 text-rose-400">
              ⚠ No OAuth secrets found. Download client_secret.json from Google Cloud
              Console and place it in <code className="rounded bg-ink-900 px-1">secrets/</code>.
            </div>
          )}
          {status.dry_run && status.has_secrets && (
            <div className="mt-1 text-amber-400">
              ⓘ Dry-run mode is ON — uploads will be simulated. Turn it OFF in Settings after connecting.
            </div>
          )}
        </div>
      )}

      {msg && (
        <div className="mt-2 text-[11px] text-zinc-300">{msg}</div>
      )}

      <div className="mt-3 flex gap-2">
        {!status.connected ? (
          <button
            className="btn-primary !px-3 !py-1 text-xs"
            onClick={start}
            disabled={busy || !status.has_secrets}
            title={!status.has_secrets ? 'Add secrets/client_secret.json first' : ''}
          >
            {busy ? 'waiting…' : '🔗 Connect YouTube'}
          </button>
        ) : (
          <>
            <button
              className="btn-ghost !px-3 !py-1 text-xs"
              onClick={refresh}
              disabled={busy}
            >
              ↻ refresh stats
            </button>
            {status.needs_reauth && (
              <button
                className="btn-primary !px-3 !py-1 text-xs"
                onClick={start}
                disabled={busy}
              >
                🔑 Re-connect YouTube
              </button>
            )}
          </>
        )}
      </div>
    </div>
  )
}

function ChannelCard({ channel, onChanged }: { channel: Channel; onChanged: () => void }) {
  const { data: strategy } = usePoll<StrategyProfile>(`/api/channels/${channel.id}/strategy`, 15000)
  const [editOpen, setEditOpen] = useState(false)

  return (
    <div className="card">
      <div className="flex items-start justify-between">
        <div className="flex items-start gap-3">
          {channel.yt_thumbnail ? (
            <img src={channel.yt_thumbnail} alt="" className="h-12 w-12 rounded-full"
              onError={(e) => { (e.target as HTMLImageElement).style.display = 'none' }} />
          ) : (
            <div className="flex h-12 w-12 items-center justify-center rounded-full bg-gradient-to-br from-phoenix-500 to-amber-500 text-lg font-black text-white">
              {channel.name.charAt(0).toUpperCase()}
            </div>
          )}
          <div>
            <div className="text-lg font-bold text-white">{channel.name}</div>
            <div className="mt-1 text-xs text-zinc-500">
              {channel.niche} · {channel.language} · {channel.videos_per_day} videos/day ·{' '}
              privacy: {channel.privacy}
            </div>
            {channel.yt_channel_id && (
              <div className="mt-1 text-[11px] text-phoenix-400">
                YT: {channel.yt_channel_id}
              </div>
            )}
          </div>
        </div>
        <StatusBadge status={channel.active ? 'published' : 'cancelled'} />
      </div>

      <YouTubeConnect channel={channel} onChanged={onChanged} />

      {strategy && Object.keys(strategy.hook_weights).length > 0 && (
        <div className="mt-4 rounded-xl bg-ink-800 p-3">
          <div className="mb-2 text-[11px] font-semibold uppercase tracking-wider text-phoenix-400">
            🧠 learned strategy
          </div>
          <div className="grid grid-cols-3 gap-2 text-center text-xs">
            <div>
              <div className="text-zinc-500">best niche</div>
              <div className="font-semibold text-zinc-200">
                {Object.entries(strategy.niche_weights).sort((a, b) => b[1] - a[1])[0]?.[0] ?? '—'}
              </div>
            </div>
            <div>
              <div className="text-zinc-500">best hook</div>
              <div className="font-semibold text-zinc-200">
                {Object.entries(strategy.hook_weights).sort((a, b) => b[1] - a[1])[0]?.[0] ?? '—'}
              </div>
            </div>
            <div>
              <div className="text-zinc-500">publish hours</div>
              <div className="font-semibold text-zinc-200">
                {strategy.publish_hours.map((h) => `${h}:00`).join(', ')}
              </div>
            </div>
          </div>
          {strategy.insights?.slice(-2).map((ins, i) => (
            <div key={i} className="mt-2 text-[11px] text-zinc-500">• {ins}</div>
          ))}
        </div>
      )}

      <div className="mt-4 flex flex-wrap gap-2">
        <button
          className="btn-ghost !px-3 !py-1 text-xs"
          onClick={async () => {
            await api.patch(`/api/channels/${channel.id}`, { active: !channel.active })
            onChanged()
          }}
        >
          {channel.active ? '⏸ pause' : '▶ resume'}
        </button>
        <Link className="btn-ghost !px-3 !py-1 text-xs" to={`/analytics?channel=${channel.id}`}>
          analytics →
        </Link>
        <button
          className="btn-ghost !px-3 !py-1 text-xs"
          onClick={() => setEditOpen((v) => !v)}
        >
          ✎ edit
        </button>
      </div>

      {editOpen && <EditChannelForm channel={channel} onDone={() => { setEditOpen(false); onChanged() }} />}
    </div>
  )
}

function EditChannelForm({ channel, onDone }: { channel: Channel; onDone: () => void }) {
  const [form, setForm] = useState({
    name: channel.name,
    niche: channel.niche,
    language: channel.language,
    videos_per_day: channel.videos_per_day,
    privacy: channel.privacy,
  })
  const [busy, setBusy] = useState(false)

  const save = async () => {
    setBusy(true)
    try {
      await api.patch(`/api/channels/${channel.id}`, form)
      onDone()
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="mt-4 space-y-2 rounded-xl border border-ink-700 bg-ink-800 p-3">
      <div className="grid gap-2 md:grid-cols-2">
        <div>
          <label className="label">Name</label>
          <input className="input" value={form.name}
            onChange={(e) => setForm({ ...form, name: e.target.value })} />
        </div>
        <div>
          <label className="label">Niche</label>
          <select className="input" value={form.niche}
            onChange={(e) => setForm({ ...form, niche: e.target.value })}>
            {NICHES.map((n) => <option key={n}>{n}</option>)}
          </select>
        </div>
        <div>
          <label className="label">Language</label>
          <select className="input" value={form.language}
            onChange={(e) => setForm({ ...form, language: e.target.value })}>
            {LANGUAGES.map((l) => <option key={l.code} value={l.code}>{l.label}</option>)}
          </select>
        </div>
        <div>
          <label className="label">Videos / day</label>
          <input className="input" type="number" min={1} max={10} value={form.videos_per_day}
            onChange={(e) => setForm({ ...form, videos_per_day: Number(e.target.value) })} />
        </div>
        <div>
          <label className="label">Privacy</label>
          <select className="input" value={form.privacy}
            onChange={(e) => setForm({ ...form, privacy: e.target.value })}>
            <option>private</option>
            <option>unlisted</option>
            <option>public</option>
          </select>
        </div>
      </div>
      <div className="flex gap-2">
        <button className="btn-primary !px-3 !py-1 text-xs" onClick={save} disabled={busy}>
          {busy ? 'saving…' : 'save'}
        </button>
        <button className="btn-ghost !px-3 !py-1 text-xs" onClick={onDone}>cancel</button>
      </div>
    </div>
  )
}

export default function ChannelsPage() {
  const { data: channels, error } = usePoll<Channel[]>('/api/channels', 6000)
  const [tick, setTick] = useState(0)

  if (error) return <div className="text-rose-400">Failed to load channels: {error}</div>

  return (
    <div>
      <PageHeader title="Channels">
        <NewChannelForm onCreated={() => setTick((t) => t + 1)} />
      </PageHeader>
      <div className="grid gap-4 lg:grid-cols-2">
        {(channels ?? []).map((c) => (
          <ChannelCard key={`${c.id}-${tick}`} channel={c} onChanged={() => setTick((t) => t + 1)} />
        ))}
      </div>
      {(channels ?? []).length === 0 && (
        <div className="card py-12 text-center text-sm text-zinc-600">
          no channels yet — create one above
        </div>
      )}
    </div>
  )
}
