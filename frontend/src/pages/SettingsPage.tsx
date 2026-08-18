import { useEffect, useState } from 'react'
import { PageHeader } from '../components/Layout'
import { api, usePoll } from '../lib/api'
import type { SettingsView } from '../lib/types'

interface FormState {
  channel_name: string
  channel_niche: string
  channel_language: string
  videos_per_day: number
  video_target_seconds: number
  video_resolution: string
  video_aspect: string
  video_privacy: string
  show_captions: boolean
  show_watermark: boolean
  show_subscribe_endcard: boolean
  show_subscribe_badge: boolean
  use_intro: boolean
  use_outro: boolean
  default_categories: string
  youtube_dry_run: boolean
  youtube_category_id: string
  tts_voice: string
  tts_rate: string
  tts_pitch: string
  // v1.3
  video_length_mode: string
  cinematic_mode: boolean
  seo_language: string
  hide_hooks_in_description: boolean
  monitor_min_views: number
  monitor_daily_quota: number
  monitor_region_code: string
  monitor_learn_from_top_videos: boolean
  copyright_check_enabled: boolean
  copyright_wait_seconds: number
  auto_publish_after_check: boolean
  post_check_privacy: string
  scheduler_auto_trigger: boolean
  // v1.6 mock/real toggles
  force_mock_llm: boolean
  force_mock_pexels: boolean
  force_mock_pixabay: boolean
  force_mock_jamendo: boolean
  force_mock_youtube: boolean
  force_mock_acoustid: boolean
  force_mock_huggingface: boolean
  force_mock_amazon: boolean
  force_mock_reddit: boolean
  force_mock_news: boolean
  fpcalc_path: string
  approval_required: boolean
  notifications_enabled: boolean
  backup_retention_days: number
  youtube_daily_quota_units: number
}

function UploadMode({ value, onChange }: { value: boolean; onChange: (v: boolean) => void }) {
  return (
    <div className="rounded-2xl border border-fuchsia-100/15 bg-black/20 p-2 shadow-[inset_0_1px_0_rgba(255,255,255,0.06)]">
      <div className="mb-2 flex items-center justify-between px-2">
        <span className="text-[10px] font-semibold uppercase tracking-[0.2em] text-fuchsia-100/55">Live publish mode</span>
        <span className={`glass-chip text-[10px] ${value ? 'text-amber-100' : 'text-emerald-100'}`}>
          <span className={`h-1.5 w-1.5 rounded-full ${value ? 'bg-amber-300' : 'bg-emerald-300'} shadow-[0_0_8px_currentColor]`} />
          {value ? 'review first' : 'automatic'}
        </span>
      </div>
      <div className="grid gap-2 sm:grid-cols-2">
        <button type="button" onClick={() => onChange(true)}
          className={`rounded-xl border px-3 py-3 text-left transition-all duration-200 ${value
            ? 'border-fuchsia-200/45 bg-gradient-to-br from-fuchsia-200/20 to-violet-300/10 text-white shadow-[0_0_24px_rgba(239,159,232,0.14)]'
            : 'border-white/8 bg-white/[0.035] text-zinc-400 hover:border-fuchsia-200/20 hover:text-fuchsia-100'}`}>
          <div className="flex items-center justify-between text-sm font-semibold"><span>✦ Manual approval</span><span>{value ? '✓' : ''}</span></div>
          <div className="mt-1 text-[11px] leading-relaxed text-white/45">Render → safety check → you approve in Safety Center → publish.</div>
        </button>
        <button type="button" onClick={() => onChange(false)}
          className={`rounded-xl border px-3 py-3 text-left transition-all duration-200 ${!value
            ? 'border-emerald-200/35 bg-gradient-to-br from-emerald-200/14 to-cyan-300/8 text-white shadow-[0_0_24px_rgba(110,231,183,0.10)]'
            : 'border-white/8 bg-white/[0.035] text-zinc-400 hover:border-emerald-200/20 hover:text-emerald-100'}`}>
          <div className="flex items-center justify-between text-sm font-semibold"><span>⚡ Automatic safe upload</span><span>{!value ? '✓' : ''}</span></div>
          <div className="mt-1 text-[11px] leading-relaxed text-white/45">System checks the render and copyright policy, then uploads automatically.</div>
        </button>
      </div>
      <div className="mt-2 rounded-xl border border-white/8 bg-white/[0.035] px-3 py-2 text-[10px] leading-relaxed text-white/45">
        Automatic mode still respects dry-run, OAuth availability, copyright checks, privacy settings and provider limits. It never bypasses those safeguards.
      </div>
    </div>
  )
}

function Toggle({ label, hint, value, onChange }: {
  label: string
  hint?: string
  value: boolean
  onChange: (v: boolean) => void
}) {
  return (
    <label className="flex cursor-pointer items-start justify-between gap-4 rounded-xl border border-white/8 bg-white/[0.035] px-3 py-2.5 transition-colors hover:border-white/15 hover:bg-white/[0.055]">
      <div>
        <div className="text-sm font-medium text-zinc-200">{label}</div>
        {hint && <div className="mt-0.5 text-[11px] text-zinc-500">{hint}</div>}
      </div>
      <button
        type="button"
        onClick={() => onChange(!value)}
        className={`relative h-6 w-11 flex-shrink-0 rounded-full border transition-all duration-200 ${
          value ? 'border-fuchsia-100/40 bg-gradient-to-r from-fuchsia-300 to-violet-400 shadow-[0_0_16px_rgba(239,159,232,0.32)]' : 'border-white/10 bg-white/10'
        }`}
      >
        <span
          className={`absolute top-0.5 h-5 w-5 rounded-full bg-white shadow transition-transform ${
            value ? 'translate-x-5' : 'translate-x-0.5'
          }`}
        />
      </button>
    </label>
  )
}

export default function SettingsPage() {
  const { data: s, error } = usePoll<SettingsView>('/api/settings', 30000)
  const [form, setForm] = useState<FormState | null>(null)
  const [saving, setSaving] = useState(false)
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null)

  useEffect(() => {
    if (!s) return
    const a = s.app
    setForm({
      channel_name: String(a.channel_name ?? ''),
      channel_niche: String(a.channel_niche ?? 'technology'),
      channel_language: String(a.channel_language ?? 'en'),
      videos_per_day: Number(a.videos_per_day ?? 3),
      video_target_seconds: Number(a.video_target_seconds ?? 150),
      video_resolution: String(a.video_resolution ?? '1080p'),
      video_aspect: String(a.video_aspect ?? 'landscape'),
      video_privacy: String(a.video_privacy ?? 'private'),
      show_captions: Boolean(a.show_captions ?? true),
      show_watermark: Boolean(a.show_watermark ?? false),
      show_subscribe_endcard: Boolean(a.show_subscribe_endcard ?? false),
      show_subscribe_badge: Boolean(a.show_subscribe_badge ?? false),
      use_intro: Boolean(a.use_intro ?? false),
      use_outro: Boolean(a.use_outro ?? false),
      default_categories: String(a.default_categories ?? 'technology,science,space'),
      youtube_dry_run: Boolean(a.youtube_dry_run ?? true),
      youtube_category_id: String(a.youtube_category_id ?? '27'),
      tts_voice: String(a.tts_voice ?? 'en-US-ChristopherNeural'),
      tts_rate: String(a.tts_rate ?? '+4%'),
      tts_pitch: String(a.tts_pitch ?? '+0Hz'),
      // v1.3
      video_length_mode: String(a.video_length_mode ?? 'manual'),
      cinematic_mode: Boolean(a.cinematic_mode ?? true),
      seo_language: String(a.seo_language ?? 'en'),
      hide_hooks_in_description: Boolean(a.hide_hooks_in_description ?? true),
      monitor_min_views: Number(a.monitor_min_views ?? 2_000_000),
      monitor_daily_quota: Number(a.monitor_daily_quota ?? 50),
      monitor_region_code: String(a.monitor_region_code ?? 'US'),
      monitor_learn_from_top_videos: Boolean(a.monitor_learn_from_top_videos ?? true),
      copyright_check_enabled: Boolean(a.copyright_check_enabled ?? true),
      copyright_wait_seconds: Number(a.copyright_wait_seconds ?? 150),
      auto_publish_after_check: Boolean(a.auto_publish_after_check ?? true),
      post_check_privacy: String(a.post_check_privacy ?? 'unlisted'),
      scheduler_auto_trigger: Boolean(a.scheduler_auto_trigger ?? true),
      // v1.6
      force_mock_llm: Boolean(a.force_mock_llm ?? false),
      force_mock_pexels: Boolean(a.force_mock_pexels ?? false),
      force_mock_pixabay: Boolean(a.force_mock_pixabay ?? false),
      force_mock_jamendo: Boolean(a.force_mock_jamendo ?? false),
      force_mock_youtube: Boolean(a.force_mock_youtube ?? false),
      force_mock_acoustid: Boolean(a.force_mock_acoustid ?? false),
      force_mock_huggingface: Boolean(a.force_mock_huggingface ?? false),
      force_mock_amazon: Boolean(a.force_mock_amazon ?? false),
      force_mock_reddit: Boolean(a.force_mock_reddit ?? false),
      force_mock_news: Boolean(a.force_mock_news ?? false),
      fpcalc_path: String(a.fpcalc_path ?? ''),
      approval_required: Boolean(a.approval_required ?? false),
      notifications_enabled: Boolean(a.notifications_enabled ?? true),
      backup_retention_days: Number(a.backup_retention_days ?? 14),
      youtube_daily_quota_units: Number(a.youtube_daily_quota_units ?? 10000),
    })
  }, [s])

  const save = async () => {
    if (!form) return
    setSaving(true)
    setMsg(null)
    try {
      const r = await api.post<{ applied: Record<string, unknown>; count: number }>(
        '/api/settings', form)
      setMsg({ ok: true, text: `Saved ${r.count} setting${r.count === 1 ? '' : 's'} to .env` })
    } catch (e) {
      setMsg({ ok: false, text: e instanceof Error ? e.message : String(e) })
    } finally {
      setSaving(false)
    }
  }

  if (error) return <div className="text-rose-400">Failed to load settings: {error}</div>
  if (!s || !form) return <div className="text-zinc-500">loading…</div>

  const set = <K extends keyof FormState>(k: K, v: FormState[K]) =>
    setForm({ ...form, [k]: v })

  return (
    <div>
      <PageHeader title="Settings">
        <button
          className="btn-primary"
          onClick={save}
          disabled={saving}
        >
          {saving ? 'saving…' : '💾 save to .env'}
        </button>
      </PageHeader>

      {msg && (
        <div className={`mb-4 rounded-lg px-4 py-2.5 text-sm ${
          msg.ok ? 'bg-emerald-500/15 text-emerald-300' : 'bg-rose-500/15 text-rose-300'
        }`}>
          {msg.text}
        </div>
      )}

      <div className="card mb-6 border-emerald-200/15 bg-emerald-300/[0.035]">
        <div className="mb-3 flex items-center justify-between">
          <div>
            <div className="text-xs font-semibold uppercase tracking-wider text-emerald-100/70">Automatic quality controls</div>
            <div className="mt-1 text-[11px] text-white/45">Render، duration، media streams، compliance اور copyright checks upload se pehle khud run hote hain۔</div>
          </div>
          <span className="glass-chip text-emerald-100"><span className="h-1.5 w-1.5 rounded-full bg-emerald-300 shadow-[0_0_8px_currentColor]" /> {form.approval_required ? 'manual review' : 'automatic'}</span>
        </div>
        <div className="grid gap-2 text-xs sm:grid-cols-3">
          <div className="rounded-xl border border-white/8 bg-black/15 px-3 py-2 text-white/65">Duration tolerance: <strong className="text-white">{String(s.app.duration_tolerance_seconds ?? 3)}s / {((Number(s.app.duration_tolerance_ratio ?? 0.08)) * 100).toFixed(0)}%</strong></div>
          <div className="rounded-xl border border-white/8 bg-black/15 px-3 py-2 text-white/65">Urdu voice rate: <strong className="text-white">{String(s.app.urdu_tts_rate ?? '-8%')}</strong></div>
          <div className="rounded-xl border border-white/8 bg-black/15 px-3 py-2 text-white/65">Critical safety gates: <strong className="text-emerald-200">ON</strong></div>
        </div>
      </div>

      <div className="grid gap-6 lg:grid-cols-2">
        {/* Channel + production defaults */}
        <div className="card">
          <div className="mb-4 text-xs font-semibold uppercase tracking-wider text-zinc-500">
            Channel & production defaults
          </div>
          <div className="space-y-3">
            <div>
              <label className="label">Channel name</label>
              <input className="input" value={form.channel_name}
                onChange={(e) => set('channel_name', e.target.value)} />
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="label">Niche</label>
                <select className="input" value={form.channel_niche}
                  onChange={(e) => set('channel_niche', e.target.value)}>
                  {s.options.niches.map((n) => <option key={n} value={n}>{n}</option>)}
                </select>
              </div>
              <div>
                <label className="label">Language</label>
                <select className="input" value={form.channel_language}
                  onChange={(e) => set('channel_language', e.target.value)}>
                  {s.options.languages.map((l) =>
                    <option key={l.code} value={l.code}>{l.label}</option>)}
                </select>
              </div>
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="label">Videos / day</label>
                <input className="input" type="number" min={1} max={10}
                  value={form.videos_per_day}
                  onChange={(e) => set('videos_per_day', Number(e.target.value))} />
              </div>
              <div>
                <label className="label">Target length (seconds)</label>
                <input className="input" type="number" min={15} max={3600}
                  value={form.video_target_seconds}
                  onChange={(e) => set('video_target_seconds', Number(e.target.value))} />
              </div>
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="label">Resolution</label>
                <select className="input" value={form.video_resolution}
                  onChange={(e) => set('video_resolution', e.target.value)}>
                  {s.options.resolutions.map((r) => <option key={r} value={r}>{r}</option>)}
                </select>
              </div>
              <div>
                <label className="label">Aspect ratio</label>
                <select className="input" value={form.video_aspect}
                  onChange={(e) => set('video_aspect', e.target.value)}>
                  {s.options.aspects.map((a) => <option key={a} value={a}>{a}</option>)}
                </select>
              </div>
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="label">Privacy</label>
                <select className="input" value={form.video_privacy}
                  onChange={(e) => set('video_privacy', e.target.value)}>
                  {s.options.privacy.map((p) => <option key={p} value={p}>{p}</option>)}
                </select>
              </div>
              <div>
                <label className="label">Default categories (comma-separated)</label>
                <input className="input" value={form.default_categories}
                  onChange={(e) => set('default_categories', e.target.value)}
                  placeholder="technology,science,space" />
              </div>
            </div>
          </div>
        </div>

        {/* Visual toggles */}
        <div className="card">
          <div className="mb-4 text-xs font-semibold uppercase tracking-wider text-zinc-500">
            Video overlays (toggleable per-video too)
          </div>
          <div className="space-y-2">
            <Toggle
              label="Subtitles / captions"
              hint="Burn styled animated captions into the video"
              value={form.show_captions}
              onChange={(v) => set('show_captions', v)} />
            <Toggle
              label="Watermark (logo)"
              hint="Overlay assets/logo.png in the top-right corner"
              value={form.show_watermark}
              onChange={(v) => set('show_watermark', v)} />
            <Toggle
              label="Subscribe end-card"
              hint="Clean (NOT green-screen) 'Subscribe' card for the last ~4s"
              value={form.show_subscribe_endcard}
              onChange={(v) => set('show_subscribe_endcard', v)} />
            <Toggle
              label="Persistent Subscribe badge"
              hint="Small pill shown in the top-right through the whole video"
              value={form.show_subscribe_badge}
              onChange={(v) => set('show_subscribe_badge', v)} />
            <Toggle
              label="Use intro.mp4"
              hint="Prepend assets/intro.mp4 if it exists"
              value={form.use_intro}
              onChange={(v) => set('use_intro', v)} />
            <Toggle
              label="Use outro.mp4"
              hint="Append assets/outro.mp4 if it exists"
              value={form.use_outro}
              onChange={(v) => set('use_outro', v)} />
          </div>
          <div className="mt-4 rounded-xl bg-ink-800 p-3 text-[11px] leading-relaxed text-zinc-500">
            Tip: the green-screen subscribe you were seeing at the end of videos is
            disabled by default. Toggle the end-card here only if you want a clean
            subscribe CTA — or use the small persistent badge instead.
          </div>
        </div>

        {/* Voice + YouTube */}
        <div className="card">
          <div className="mb-4 text-xs font-semibold uppercase tracking-wider text-zinc-500">
            Voice & YouTube
          </div>
          <div className="space-y-3">
            <div>
              <label className="label">TTS voice</label>
              <input className="input" value={form.tts_voice}
                onChange={(e) => set('tts_voice', e.target.value)} />
              <div className="mt-1 text-[10px] text-zinc-600">
                Pick from the voices table below (e.g. ur-PK-AsadNeural for Urdu).
                When you change the language on a video, the right voice is picked
                automatically — you can leave this blank by setting it to the
                channel's default language voice.
              </div>
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="label">TTS rate</label>
                <input className="input" value={form.tts_rate}
                  onChange={(e) => set('tts_rate', e.target.value)}
                  placeholder="+4%" />
              </div>
              <div>
                <label className="label">TTS pitch</label>
                <input className="input" value={form.tts_pitch}
                  onChange={(e) => set('tts_pitch', e.target.value)}
                  placeholder="+0Hz" />
              </div>
            </div>
            <Toggle
              label="YouTube dry-run mode"
              hint="When ON, uploads are simulated (manifest files only). Turn OFF after OAuth to upload for real."
              value={form.youtube_dry_run}
              onChange={(v) => set('youtube_dry_run', v)} />
            <div>
              <label className="label">YouTube category ID</label>
              <input className="input" value={form.youtube_category_id}
                onChange={(e) => set('youtube_category_id', e.target.value)} />
              <div className="mt-1 text-[10px] text-zinc-600">
                27 = Education, 28 = Science & Technology, 22 = People & Blogs, 24 = Entertainment
              </div>
            </div>
          </div>
        </div>

        {/* v1.3 Production mode */}
        <div className="card">
          <div className="mb-4 text-xs font-semibold uppercase tracking-wider text-zinc-500">
            Production mode (v1.3)
          </div>
          <div className="space-y-3">
            <div>
              <label className="label">Default video length mode</label>
              <select className="input" value={form.video_length_mode}
                onChange={(e) => set('video_length_mode', e.target.value)}>
                <option value="manual">Manual — use target seconds</option>
                <option value="shorts">Shorts — random 30s–3min (portrait)</option>
                <option value="long">Long — random 3–10min (landscape)</option>
              </select>
              <div className="mt-1 text-[10px] text-zinc-600">
                Used as the default when a production doesn't specify a length mode.
              </div>
            </div>
            <Toggle
              label="Cinematic mode"
              hint="Stronger color grade, slower fades, letterbox bars on landscape (movie-like)"
              value={form.cinematic_mode}
              onChange={(v) => set('cinematic_mode', v)} />
            <Toggle
              label="Hide hooks in description"
              hint="Description tells viewers WHAT the video covers without revealing the curiosity gap — competitors can't reverse-engineer your retention strategy"
              value={form.hide_hooks_in_description}
              onChange={(v) => set('hide_hooks_in_description', v)} />
            <div>
              <label className="label">SEO language (tags + description)</label>
              <select className="input" value={form.seo_language}
                onChange={(e) => set('seo_language', e.target.value)}>
                <option value="en">English (recommended — maximises reach)</option>
                <option value="ur">Urdu</option>
                <option value="hi">Hindi</option>
                <option value="es">Spanish</option>
                <option value="ar">Arabic</option>
              </select>
              <div className="mt-1 text-[10px] text-zinc-600">
                Tags + descriptions are always written in this language regardless of
                the narration language.
              </div>
            </div>
          </div>
        </div>

        {/* v1.3 YouTube monitor */}
        <div className="card">
          <div className="mb-4 text-xs font-semibold uppercase tracking-wider text-zinc-500">
            YouTube monitor
          </div>
          <div className="space-y-3">
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="label">Min views threshold</label>
                <select className="input" value={form.monitor_min_views}
                  onChange={(e) => set('monitor_min_views', Number(e.target.value))}>
                  <option value={1_000_000}>1M+ views</option>
                  <option value={2_000_000}>2M+ views</option>
                  <option value={5_000_000}>5M+ views</option>
                  <option value={10_000_000}>10M+ views</option>
                  <option value={50_000_000}>50M+ views</option>
                  <option value={100_000_000}>100M+ views</option>
                </select>
              </div>
              <div>
                <label className="label">Daily quota (videos analyzed)</label>
                <input className="input" type="number" min={1} max={500}
                  value={form.monitor_daily_quota}
                  onChange={(e) => set('monitor_daily_quota', Number(e.target.value))} />
              </div>
            </div>
            <div>
              <label className="label">Region code</label>
              <select className="input" value={form.monitor_region_code}
                onChange={(e) => set('monitor_region_code', e.target.value)}>
                {['US', 'GB', 'IN', 'PK', 'AE', 'CA', 'AU', 'DE', 'FR',
                  'BR', 'JP', 'KR', 'ID', 'TR', 'SA'].map((r) =>
                  <option key={r} value={r}>{r}</option>)}
              </select>
            </div>
            <Toggle
              label="Learn from top videos"
              hint="Extract hooks / tags / title patterns from each trending video via the LLM"
              value={form.monitor_learn_from_top_videos}
              onChange={(v) => set('monitor_learn_from_top_videos', v)} />
          </div>
        </div>

        {/* v1.6 Mock/Real API toggles */}
        <div className="card">
          <div className="mb-4 text-xs font-semibold uppercase tracking-wider text-zinc-500">
            API mock/real toggles (force any API into mock mode)
          </div>
          <div className="space-y-2">
            <Toggle
              label="LLM (OpenRouter/Gemini/Grok)"
              hint="Force mock — uses template scripts instead of LLM"
              value={form.force_mock_llm}
              onChange={(v) => set('force_mock_llm', v)} />
            <Toggle
              label="Pexels (stock videos)"
              hint="Force mock — generates gradient clips instead"
              value={form.force_mock_pexels}
              onChange={(v) => set('force_mock_pexels', v)} />
            <Toggle
              label="Pixabay (stock videos)"
              hint="Force mock — generates gradient clips instead"
              value={form.force_mock_pixabay}
              onChange={(v) => set('force_mock_pixabay', v)} />
            <Toggle
              label="Jamendo (music)"
              hint="Force mock — synthesizes ambient bed instead"
              value={form.force_mock_jamendo}
              onChange={(v) => set('force_mock_jamendo', v)} />
            <Toggle
              label="YouTube (uploads + analytics)"
              hint="Force mock — dry-run manifest only"
              value={form.force_mock_youtube}
              onChange={(v) => set('force_mock_youtube', v)} />
            <Toggle
              label="AcoustID (copyright check)"
              hint="Force mock — skips pre-upload fingerprint check"
              value={form.force_mock_acoustid}
              onChange={(v) => set('force_mock_acoustid', v)} />
            <Toggle
              label="Hugging Face (CTR prediction)"
              hint="Force mock — disables thumbnail CTR scoring"
              value={form.force_mock_huggingface}
              onChange={(v) => set('force_mock_huggingface', v)} />
            <Toggle
              label="Amazon Associates (affiliate links)"
              hint="Force mock — no affiliate links in descriptions"
              value={form.force_mock_amazon}
              onChange={(v) => set('force_mock_amazon', v)} />
            <Toggle
              label="Reddit (trend discovery)"
              hint="Force mock — no Reddit trends"
              value={form.force_mock_reddit}
              onChange={(v) => set('force_mock_reddit', v)} />
            <Toggle
              label="News API (trend discovery)"
              hint="Force mock — no news trends"
              value={form.force_mock_news}
              onChange={(v) => set('force_mock_news', v)} />
          </div>
        </div>

        {/* v1.6 Chromaprint / fpcalc setup */}
        <div className="card">
          <div className="mb-4 text-xs font-semibold uppercase tracking-wider text-zinc-500">
            Chromaprint (fpcalc) — for pre-upload copyright check
          </div>
          <div className="space-y-3">
            <div>
              <label className="label">fpcalc path (optional — leave empty for auto-detect)</label>
              <input className="input" value={form.fpcalc_path}
                onChange={(e) => set('fpcalc_path', e.target.value)}
                placeholder="e.g. C:\chromaprint\fpcalc.exe" />
              <div className="mt-1 text-[10px] text-zinc-600">
                Status: {s.app.fpcalc_available ? '✓ found' : '✗ not found'}
              </div>
            </div>
            <div className="rounded-xl bg-ink-800 p-3 text-[11px] leading-relaxed text-zinc-500">
              <strong className="text-zinc-300">How to install fpcalc on Windows:</strong>
              <ol className="mt-1 ml-4 list-decimal space-y-0.5">
                <li>Download chromaprint-tools from https://acoustid.org/chromaprint</li>
                <li>Extract the zip — find <code className="rounded bg-ink-900 px-1">fpcalc.exe</code> inside</li>
                <li>Put <code className="rounded bg-ink-900 px-1">fpcalc.exe</code> in the project's <code className="rounded bg-ink-900 px-1">secrets/</code> folder, OR</li>
                <li>Set the full path above (e.g. <code className="rounded bg-ink-900 px-1">C:\chromaprint\fpcalc.exe</code>), OR</li>
                <li>Add the folder to your system PATH</li>
              </ol>
              <div className="mt-1">YouTube credential type: <strong className="text-zinc-300">{s.app.credential_type}</strong></div>
            </div>
          </div>
        </div>

        {/* v1.3 Upload safety + scheduling */}
        <div className="card">
          <div className="mb-4 text-xs font-semibold uppercase tracking-wider text-zinc-500">
            Upload safety & scheduling (v1.3)
          </div>
          <div className="space-y-3">
            <Toggle
              label="Copyright check enabled"
              hint="After upload: wait → check for Content ID claims → delete if claimed, publish if clean"
              value={form.copyright_check_enabled}
              onChange={(v) => set('copyright_check_enabled', v)} />
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="label">Wait before check (seconds)</label>
                <input className="input" type="number" min={30} max={3600}
                  value={form.copyright_wait_seconds}
                  onChange={(e) => set('copyright_wait_seconds', Number(e.target.value))} />
                <div className="mt-1 text-[10px] text-zinc-600">Default 150s (2.5min)</div>
              </div>
              <div>
                <label className="label">Post-check privacy</label>
                <select className="input" value={form.post_check_privacy}
                  onChange={(e) => set('post_check_privacy', e.target.value)}>
                  <option value="private">private</option>
                  <option value="unlisted">unlisted</option>
                  <option value="public">public</option>
                </select>
              </div>
            </div>
            <Toggle
              label="Auto-publish after check"
              hint="When ON: clean videos are switched to the post-check privacy. When OFF: they stay unlisted."
              value={form.auto_publish_after_check}
              onChange={(v) => set('auto_publish_after_check', v)} />
            <Toggle
              label="Scheduler auto-trigger"
              hint="When ON: scheduled slots fire automatically at their time. When OFF: slots must be fired manually."
              value={form.scheduler_auto_trigger}
              onChange={(v) => set('scheduler_auto_trigger', v)} />
          </div>
        </div>

        {/* Production Safety Pack */}
        <div className="card">
          <div className="mb-4 flex items-start justify-between gap-3">
            <div>
              <div className="text-[10px] font-semibold uppercase tracking-[0.22em] text-fuchsia-100/55">Production Safety Pack</div>
              <div className="mt-1 text-lg font-semibold text-white">Choose how live videos leave the studio</div>
            </div>
            <span className="glass-chip text-[10px] text-fuchsia-100/70">policy gate</span>
          </div>
          <div className="space-y-3">
            <UploadMode value={form.approval_required} onChange={(v) => set('approval_required', v)} />
            <Toggle
              label="Enable notifications"
              hint="Records alerts in the dashboard; optional webhook delivery is configured outside the UI."
              value={form.notifications_enabled}
              onChange={(v) => set('notifications_enabled', v)} />
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="label">Backup retention (days)</label>
                <input className="input" type="number" min={1} max={365}
                  value={form.backup_retention_days}
                  onChange={(e) => set('backup_retention_days', Number(e.target.value))} />
              </div>
              <div>
                <label className="label">YouTube local quota budget</label>
                <input className="input" type="number" min={1000} max={100000}
                  value={form.youtube_daily_quota_units}
                  onChange={(e) => set('youtube_daily_quota_units', Number(e.target.value))} />
              </div>
            </div>
            <div className="rounded-xl bg-ink-800 p-3 text-[11px] leading-relaxed text-zinc-500">
              Provider-side quota and balance remain authoritative. Phoenix never presents a local estimate as a guaranteed remaining quota.
            </div>
          </div>
        </div>

        {/* Capabilities */}
        <div className="space-y-6">
          <div className="card">
            <div className="mb-4 text-xs font-semibold uppercase tracking-wider text-zinc-500">
              Service capabilities
            </div>
            <div className="space-y-2 text-sm">
              {Object.entries(s.capabilities).map(([k, v]) => (
                <div key={k} className="flex items-center justify-between rounded-lg bg-ink-800 px-3 py-2">
                  <span className="font-semibold text-zinc-300">{k}</span>
                  <span className={v.startsWith('live') ? 'text-emerald-400' : 'text-amber-400'}>
                    {v}
                  </span>
                </div>
              ))}
              <div className="flex items-center justify-between rounded-lg bg-ink-800 px-3 py-2">
                <span className="font-semibold text-zinc-300">ffmpeg</span>
                <span className={s.ffmpeg === 'ok' ? 'text-emerald-400' : 'text-rose-400'}>
                  {s.ffmpeg}
                </span>
              </div>
            </div>
          </div>

          <div className="card">
            <div className="mb-4 text-xs font-semibold uppercase tracking-wider text-zinc-500">
              API keys (masked — edit in .env)
            </div>
            <div className="space-y-2 font-mono text-sm">
              {Object.entries(s.keys_masked).map(([k, v]) => (
                <div key={k} className="flex items-center justify-between">
                  <span className="text-zinc-400">{k}</span>
                  <span className={v ? 'text-zinc-200' : 'text-zinc-600'}>{v || 'not set'}</span>
                </div>
              ))}
            </div>
          </div>
        </div>

        {/* Voices reference */}
        <div className="card lg:col-span-2">
          <div className="mb-4 text-xs font-semibold uppercase tracking-wider text-zinc-500">
            Voices (Edge-TTS, free) — pick one for TTS_VOICE
          </div>
          <div className="grid grid-cols-2 gap-1 text-xs md:grid-cols-3 lg:grid-cols-4">
            {Object.entries(s.voices).map(([lang, voice]) => (
              <div key={lang} className="flex justify-between rounded bg-ink-800 px-2 py-1">
                <span className="text-zinc-400">{lang}</span>
                <span className="text-zinc-500">{voice}</span>
              </div>
            ))}
          </div>
          <p className="mt-4 rounded-xl bg-ink-800 p-3 text-xs leading-relaxed text-zinc-500">
            {s.note}
          </p>
        </div>
      </div>
    </div>
  )
}
