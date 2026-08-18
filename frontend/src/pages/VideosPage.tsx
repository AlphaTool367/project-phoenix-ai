import { useState } from 'react'
import { PageHeader } from '../components/Layout'
import StatusBadge from '../components/StatusBadge'
import { api, timeAgo, usePoll } from '../lib/api'
import type { Channel, SettingsView, Video, YouTubeCategory } from '../lib/types'

const RESOLUTIONS = ['480p', '720p', '1080p', '1440p', '4k'] as const
const ASPECTS = ['landscape', 'square', 'portrait'] as const
const LENGTH_PRESETS = [30, 60, 120, 180, 300, 600] as const
const NICHES = ['technology', 'finance', 'health', 'space', 'history', 'science',
  'education', 'entertainment', 'gaming', 'lifestyle', 'news', 'music']

function Toggle({ label, value, onChange }: {
  label: string
  value: boolean
  onChange: (v: boolean) => void
}) {
  return (
    <label className="flex cursor-pointer items-center justify-between gap-3 rounded-lg bg-ink-800 px-3 py-2">
      <span className="text-xs text-zinc-300">{label}</span>
      <button
        type="button"
        onClick={() => onChange(!value)}
        className={`relative h-5 w-10 flex-shrink-0 rounded-full transition-colors ${
          value ? 'bg-phoenix-500' : 'bg-ink-600'
        }`}
      >
        <span
          className={`absolute top-0.5 h-4 w-4 rounded-full bg-white shadow transition-transform ${
            value ? 'translate-x-5' : 'translate-x-0.5'
          }`}
        />
      </button>
    </label>
  )
}

function ProduceForm({ channels, onStarted }: { channels: Channel[]; onStarted: () => void }) {
  const { data: settings } = usePoll<SettingsView>('/api/settings', 30000)
  const [channelId, setChannelId] = useState<number>(channels[0]?.id ?? 1)
  const [topic, setTopic] = useState('')
  const [busy, setBusy] = useState(false)
  const [resolution, setResolution] = useState<string>('1080p')
  const [aspect, setAspect] = useState<string>('landscape')
  const [targetSeconds, setTargetSeconds] = useState<number>(150)
  const [language, setLanguage] = useState<string>('')
  const [categories, setCategories] = useState<string[]>([])
  const [youtubeCategory, setYoutubeCategory] = useState<string>('27')
  const [showAdvanced, setShowAdvanced] = useState(false)
  // v1.3: length mode — 'manual' | 'shorts' | 'long' | '' (use global default)
  const [lengthMode, setLengthMode] = useState<string>('')

  // Per-video overrides (null = use global default)
  const [showCaptions, setShowCaptions] = useState<boolean | null>(null)
  const [showWatermark, setShowWatermark] = useState<boolean | null>(null)
  const [showEndcard, setShowEndcard] = useState<boolean | null>(null)
  const [showBadge, setShowBadge] = useState<boolean | null>(null)
  // v1.4: clip Shorts from a long video after it renders
  const [clipShorts, setClipShorts] = useState<boolean>(false)
  // v1.7: manual scene count override (null = auto)
  const [sceneCount, setSceneCount] = useState<number | null>(null)

  // Fetch YouTube categories when channel changes
  const { data: ytCats } = usePoll<YouTubeCategory[]>(
    `/api/channels/${channelId}/categories`, 60000)

  const toggleCategory = (c: string) => {
    setCategories((cur) => cur.includes(c) ? cur.filter((x) => x !== c) : [...cur, c])
  }

  const start = async () => {
    setBusy(true)
    try {
      await api.post('/api/videos/produce', {
        channel_id: channelId,
        topic: topic.trim() || null,
        publish: true,
        resolution,
        aspect,
        // When length_mode is set (shorts/long), don't send target_seconds —
        // the backend resolves it randomly within the right band.
        target_seconds: lengthMode ? null : targetSeconds,
        length_mode: lengthMode || null,
        categories: categories.length > 0 ? categories : null,
        language: language || null,
        show_captions: showCaptions,
        show_watermark: showWatermark,
        show_subscribe_endcard: showEndcard,
        show_subscribe_badge: showBadge,
        youtube_category_id: youtubeCategory,
        // v1.4: only clip Shorts when in long mode (Shorts-from-Shorts makes no sense)
        clip_shorts: clipShorts && lengthMode === 'long',
        // v1.7: manual scene count override
        scene_count: sceneCount,
      })
      setTopic('')
      onStarted()
    } finally {
      setBusy(false)
    }
  }

  const defCats = (settings?.app.default_categories as string) || 'technology,science,space'
  const catOptions = Array.from(new Set([
    ...NICHES,
    ...defCats.split(',').map((c) => c.trim()).filter(Boolean),
  ]))

  // When length mode is shorts/long, show a hint about what duration will be picked.
  const lengthHint = lengthMode === 'shorts'
    ? 'Shorts: random 30s–3min (portrait recommended)'
    : lengthMode === 'long'
    ? 'Long: random 3–10min (landscape recommended)'
    : null

  return (
    <div className="card mb-6">
              <div className="mb-3 flex items-center justify-between gap-3">
          <div>
            <div className="text-[10px] font-semibold uppercase tracking-[0.2em] text-fuchsia-100/55">Produce a video now</div>
            {settings && (
              <div className="mt-1 flex items-center gap-2 text-[11px] text-white/45">
                <span className={`h-1.5 w-1.5 rounded-full ${settings.app.approval_required ? 'bg-amber-300' : 'bg-emerald-300'} shadow-[0_0_8px_currentColor]`} />
                {settings.app.approval_required ? 'Manual approval before live upload' : 'Automatic safe upload after checks'}
              </div>
            )}
          </div>
          <button

          type="button"
          className="text-xs text-zinc-400 hover:text-zinc-200"
          onClick={() => setShowAdvanced((v) => !v)}
        >
          {showAdvanced ? '▾ hide options' : '▸ advanced options'}
        </button>
      </div>
      <div className="flex flex-wrap items-end gap-3">
        <div className="w-48">
          <label className="label">Channel</label>
          <select className="input" value={channelId}
            onChange={(e) => setChannelId(Number(e.target.value))}>
            {channels.map((c) => (
              <option key={c.id} value={c.id}>{c.name}</option>
            ))}
          </select>
        </div>
        <div className="min-w-64 flex-1">
          <label className="label">Topic (optional — AI picks if empty)</label>
          <input className="input" value={topic} onChange={(e) => setTopic(e.target.value)}
            placeholder="e.g. Why the ocean is deeper than space" />
        </div>
        <button className="btn-primary" onClick={start} disabled={busy}>
          {busy ? 'starting…' : '▶ Start production'}
        </button>
      </div>

      {/* v1.3: Length mode picker — always visible, primary control */}
      <div className="mt-4">
        <label className="label">Video length mode</label>
        <div className="flex flex-wrap gap-2">
          <LengthModeBtn label="Manual" hint="Use exact target seconds"
            active={lengthMode === '' || lengthMode === 'manual'}
            onClick={() => setLengthMode('')} />
          <LengthModeBtn label="Shorts" hint="Random 30s–3min · portrait"
            active={lengthMode === 'shorts'}
            onClick={() => { setLengthMode('shorts'); setAspect('portrait') }} />
          <LengthModeBtn label="Long" hint="Random 3–10min · landscape"
            active={lengthMode === 'long'}
            onClick={() => { setLengthMode('long'); setAspect('landscape') }} />
        </div>
        {lengthHint && (
          <div className="mt-1 text-[11px] text-phoenix-300">{lengthHint}</div>
        )}
      </div>

      {/* Category multi-select — always visible */}
      <div className="mt-4">
        <label className="label">
          Categories (auto-discovers topics in these niches)
        </label>
        <div className="flex flex-wrap gap-1.5">
          {catOptions.map((c) => (
            <button
              key={c}
              type="button"
              onClick={() => toggleCategory(c)}
              className={`rounded-full px-3 py-1 text-xs font-semibold transition-colors ${
                categories.includes(c)
                  ? 'bg-phoenix-500/30 text-phoenix-200 ring-1 ring-phoenix-400'
                  : 'bg-ink-700 text-zinc-400 hover:bg-ink-600 hover:text-zinc-200'
              }`}
            >
              {c}
            </button>
          ))}
        </div>
        <div className="mt-1 text-[10px] text-zinc-600">
          {categories.length === 0
            ? 'No categories selected — uses the channel niche.'
            : `${categories.length} selected: ${categories.join(', ')}`}
        </div>
      </div>

      {showAdvanced && (
        <div className="mt-4 space-y-4 border-t border-ink-700 pt-4">
          <div className="grid gap-4 md:grid-cols-3">
            <div>
              <label className="label">Resolution</label>
              <select className="input" value={resolution}
                onChange={(e) => setResolution(e.target.value)}
                disabled={!!lengthMode}>
                {RESOLUTIONS.map((r) => (
                  <option key={r} value={r}>{r}</option>
                ))}
              </select>
              <div className="mt-1 text-[10px] text-zinc-600">
                {lengthMode ? 'Locked by length mode' : 'Higher = sharper but slower to render'}
              </div>
            </div>
            <div>
              <label className="label">Aspect ratio</label>
              <select className="input" value={aspect}
                onChange={(e) => setAspect(e.target.value)}>
                {ASPECTS.map((a) => (
                  <option key={a} value={a}>
                    {a === 'landscape' ? 'Landscape (16:9 — YouTube long-form)'
                     : a === 'square' ? 'Square (1:1 — Feed)'
                     : 'Portrait (9:16 — Shorts / Reels / TikTok)'}
                  </option>
                ))}
              </select>
            </div>
            <div>
              <label className="label">Target length (seconds)</label>
              <select className="input" value={targetSeconds}
                onChange={(e) => setTargetSeconds(Number(e.target.value))}
                disabled={!!lengthMode}>
                {LENGTH_PRESETS.map((s) => (
                  <option key={s} value={s}>
                    {s < 60 ? `${s}s` : `${Math.floor(s / 60)}m${s % 60 ? ` ${s % 60}s` : ''}`}
                  </option>
                ))}
              </select>
              {lengthMode && (
                <div className="mt-1 text-[10px] text-zinc-600">
                  Locked — length mode overrides this
                </div>
              )}
            </div>
          </div>

          <div className="grid gap-4 md:grid-cols-2">
            <div>
              <label className="label">Language override (optional)</label>
              <select className="input" value={language}
                onChange={(e) => setLanguage(e.target.value)}>
                <option value="">— use channel default —</option>
                {(settings?.options.languages ?? []).map((l) =>
                  <option key={l.code} value={l.code}>{l.label}</option>)}
              </select>
              <div className="mt-1 text-[10px] text-zinc-600">
                Voice auto-changes with language (Urdu → ur-PK-AsadNeural, etc.)
              </div>
            </div>
            <div>
              <label className="label">YouTube category</label>
              <select className="input" value={youtubeCategory}
                onChange={(e) => setYoutubeCategory(e.target.value)}>
                {(ytCats ?? []).map((c) => (
                  <option key={c.id} value={c.id}>{c.id} — {c.title}</option>
                ))}
              </select>
            </div>
          </div>

          {/* v1.7: Scene count selector */}
          <div>
            <label className="label">Scene count (number of clips/media segments)</label>
            <select className="input" value={sceneCount ?? ''}
              onChange={(e) => setSceneCount(e.target.value ? Number(e.target.value) : null)}>
              <option value="">— auto (based on video length) —</option>
              {[3, 4, 5, 6, 7, 8, 9, 10, 11, 12].map((n) => (
                <option key={n} value={n}>{n} scenes</option>
              ))}
            </select>
            <div className="mt-1 text-[10px] text-zinc-600">
              Each scene gets its own different stock footage clip + narration segment.
              More scenes = more visual variety. Default: auto (1 scene per ~25s).
            </div>
          </div>

          {/* Per-video visual overrides */}
          <div>
            <label className="label">
              Visual overlays (override global default — leave neutral to use it)
            </label>
            <div className="grid gap-2 md:grid-cols-2 lg:grid-cols-4">
              <TriToggle label="Captions" value={showCaptions} onChange={setShowCaptions} />
              <TriToggle label="Watermark" value={showWatermark} onChange={setShowWatermark} />
              <TriToggle label="End-card" value={showEndcard} onChange={setShowEndcard} />
              <TriToggle label="Subscribe badge" value={showBadge} onChange={setShowBadge} />
            </div>
          </div>

          {/* v1.4: clip Shorts toggle — only enabled in long mode */}
          <div>
            <label className="flex cursor-pointer items-start justify-between gap-4 rounded-lg bg-ink-800 px-3 py-2.5">
              <div>
                <div className="text-sm font-medium text-zinc-200">
                  ✂ Auto-clip Shorts after render
                </div>
                <div className="mt-0.5 text-[11px] text-zinc-500">
                  When this is a Long video, automatically clip {settings?.app.shorts_per_long ?? 3} Shorts
                  from the most engaging moments. (Only applies in Long mode.)
                </div>
              </div>
              <button
                type="button"
                onClick={() => setClipShorts((v) => !v)}
                disabled={lengthMode !== 'long'}
                className={`relative h-6 w-11 flex-shrink-0 rounded-full transition-colors ${
                  clipShorts && lengthMode === 'long' ? 'bg-phoenix-500' : 'bg-ink-600'
                } ${lengthMode !== 'long' ? 'opacity-40' : ''}`}
              >
                <span
                  className={`absolute top-0.5 h-5 w-5 rounded-full bg-white shadow transition-transform ${
                    clipShorts && lengthMode === 'long' ? 'translate-x-5' : 'translate-x-0.5'
                  }`}
                />
              </button>
            </label>
          </div>
        </div>
      )}
    </div>
  )
}

function LengthModeBtn({ label, hint, active, onClick }: {
  label: string
  hint: string
  active: boolean
  onClick: () => void
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`flex-1 rounded-lg border px-3 py-2 text-left transition-colors ${
        active
          ? 'border-phoenix-400 bg-phoenix-500/15 text-phoenix-200'
          : 'border-ink-600 bg-ink-800 text-zinc-400 hover:border-ink-500 hover:text-zinc-200'
      }`}
    >
      <div className="text-sm font-semibold">{label}</div>
      <div className="mt-0.5 text-[10px] text-zinc-500">{hint}</div>
    </button>
  )
}

function TriToggle({ label, value, onChange }: {
  label: string
  value: boolean | null
  onChange: (v: boolean | null) => void
}) {
  const state = value === null ? 'auto' : value ? 'on' : 'off'
  return (
    <div className="rounded-lg bg-ink-800 px-2 py-2">
      <div className="mb-1.5 text-xs font-medium text-zinc-300">{label}</div>
      <div className="flex gap-1">
        {(['off', 'auto', 'on'] as const).map((s) => (
          <button
            key={s}
            type="button"
            onClick={() => onChange(s === 'auto' ? null : s === 'on')}
            className={`flex-1 rounded px-1.5 py-1 text-[10px] font-semibold uppercase transition-colors ${
              state === s
                ? s === 'on' ? 'bg-emerald-500/30 text-emerald-200'
                  : s === 'off' ? 'bg-rose-500/30 text-rose-200'
                  : 'bg-zinc-500/30 text-zinc-200'
                : 'bg-ink-700 text-zinc-500 hover:text-zinc-300'
            }`}
          >
            {s}
          </button>
        ))}
      </div>
    </div>
  )
}

export default function VideosPage() {
  const { data: channels } = usePoll<Channel[]>('/api/channels', 10000)
  const [filter, setFilter] = useState('')
  const { data: videos } = usePoll<Video[]>(
    `/api/videos?limit=100${filter ? `&status=${filter}` : ''}`, 4000,
  )

  const act = async (id: number, action: 'retry' | 'cancel') => {
    await api.post(`/api/videos/${id}/${action}`)
  }

  return (
    <div>
      <PageHeader title="Videos" />
      {channels && channels.length > 0 && (
        <ProduceForm channels={channels} onStarted={() => setFilter('')} />
      )}

      <div className="mb-4 flex gap-2">
        {['', 'rendering', 'published', 'scheduled', 'failed'].map((s) => (
          <button key={s} onClick={() => setFilter(s)}
            className={`rounded-full px-3 py-1 text-xs font-semibold transition-colors ${
              filter === s ? 'bg-phoenix-500/20 text-phoenix-300' : 'bg-ink-700 text-zinc-400 hover:text-zinc-200'
            }`}>
            {s || 'all'}
          </button>
        ))}
      </div>

      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
        {(videos ?? []).map((v) => (
          <div key={v.id} className="card !p-0 overflow-hidden">
            <div className="relative aspect-video bg-ink-800">
              <img
                src={`/api/videos/${v.id}/thumbnail/0`}
                alt=""
                className="h-full w-full object-cover"
                onError={(e) => { (e.target as HTMLImageElement).style.display = 'none' }}
              />
              <div className="absolute right-2 top-2"><StatusBadge status={v.status} /></div>
              {v.categories && v.categories.length > 0 && (
                <div className="absolute left-2 top-2 flex flex-wrap gap-1">
                  {v.categories.slice(0, 3).map((c) => (
                    <span key={c} className="rounded bg-black/60 px-1.5 py-0.5 text-[9px] font-medium text-phoenix-200">
                      {c}
                    </span>
                  ))}
                </div>
              )}
            </div>
            <div className="p-4">
              <div className="truncate text-sm font-semibold text-white">{v.title || v.topic}</div>
              <div className="mt-1 text-xs text-zinc-500">
                #{v.id} · {v.niche} · {v.duration_seconds ? `${Math.round(v.duration_seconds)}s · ` : ''}
                {timeAgo(v.created_at)}
                {v.is_short && <span className="ml-1 text-phoenix-400">· SHORT</span>}
              </div>

              {/* v1.4 monetization badges */}
              <div className="mt-2 flex flex-wrap gap-1">
                {v.hook_score != null && (
                  <span className={`rounded px-1.5 py-0.5 text-[9px] font-semibold ${
                    v.hook_score >= 80 ? 'bg-emerald-500/20 text-emerald-300'
                    : v.hook_score >= 60 ? 'bg-amber-500/20 text-amber-300'
                    : 'bg-rose-500/20 text-rose-300'
                  }`} title="Hook score (0-100)">
                    🎣 hook {v.hook_score}
                  </span>
                )}
                {v.predicted_ctr != null && (
                  <span className="rounded bg-phoenix-500/20 px-1.5 py-0.5 text-[9px] font-semibold text-phoenix-300"
                    title="Predicted CTR (0-100)">
                    🎯 CTR {v.predicted_ctr}
                  </span>
                )}
                {v.copyright_check_passed != null && (
                  <span className={`rounded px-1.5 py-0.5 text-[9px] font-semibold ${
                    v.copyright_check_passed
                      ? 'bg-emerald-500/20 text-emerald-300'
                      : 'bg-rose-500/20 text-rose-300'
                  }`} title={`Copyright check: ${v.copyright_check_passed ? 'clean' : 'flagged'}`}>
                    {v.copyright_check_passed ? '✓ copyright' : '⚠ copyright'}
                  </span>
                )}
              </div>

              {v.error && (
                <div className="mt-2 rounded-lg bg-rose-500/10 px-2 py-1 text-[11px] text-rose-400 line-clamp-2">
                  {v.error}
                </div>
              )}
              <div className="mt-3 flex flex-wrap gap-2">
                {v.status === 'failed' && (
                  <button className="btn-ghost !px-3 !py-1 text-xs" onClick={() => act(v.id, 'retry')}>
                    ↻ retry
                  </button>
                )}
                {['planned', 'rendering', 'failed'].includes(v.status) && (
                  <button className="btn-ghost !px-3 !py-1 text-xs" onClick={() => act(v.id, 'cancel')}>
                    ✕ cancel
                  </button>
                )}
                {/* v1.4: clip Shorts button (only on long rendered videos) */}
                {!v.is_short && v.file_path && v.duration_seconds >= 60 && (
                  <button
                    className="btn-ghost !px-3 !py-1 text-xs"
                    onClick={async () => {
                      try { await api.post(`/api/videos/${v.id}/clip-shorts`) }
                      catch (e) { alert(e instanceof Error ? e.message : String(e)) }
                    }}
                    title="Clip Shorts from this long video"
                  >
                    ✂ clip Shorts
                  </button>
                )}
                {v.yt_video_id && !v.yt_video_id.startsWith('DRYRUN') && (
                  <a className="btn-ghost !px-3 !py-1 text-xs"
                    href={`https://youtu.be/${v.yt_video_id}`} target="_blank" rel="noreferrer">
                    open on YouTube ↗
                  </a>
                )}
                {v.file_path && (
                  <a className="btn-ghost !px-3 !py-1 text-xs" href={`/api/videos/${v.id}/file`}>
                    download
                  </a>
                )}
              </div>
            </div>
          </div>
        ))}
      </div>
      {(videos ?? []).length === 0 && (
        <div className="card py-12 text-center text-sm text-zinc-600">
          nothing here yet — start a production above
        </div>
      )}
    </div>
  )
}
