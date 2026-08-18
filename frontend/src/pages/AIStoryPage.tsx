import { useState } from 'react'
import { PageHeader } from '../components/Layout'
import { api, usePoll } from '../lib/api'
import type { Channel } from '../lib/types'

const GENRES = [
  { value: 'kids_fairy_tale', label: '🧚 Fairy Tale', desc: 'Magical fairy tale with moral lesson' },
  { value: 'moral_story', label: '📖 Moral Story', desc: 'Teaches a life lesson' },
  { value: 'bedtime_story', label: '🌙 Bedtime Story', desc: 'Calming story for children' },
  { value: 'adventure', label: '🗺️ Adventure', desc: 'Exciting hero adventure' },
  { value: 'animal_tale', label: '🐰 Animal Tale', desc: 'Animals as main characters' },
  { value: 'fable', label: '🦊 Fable', desc: 'Classic-style fable' },
  { value: 'scifi_short', label: '🚀 Sci-Fi', desc: 'Short sci-fi story' },
  { value: 'mystery', label: '🔍 Mystery', desc: 'Mystery with twist ending' },
]

const LANGUAGES = [
  { code: 'en', label: 'English' },
  { code: 'ur', label: 'Urdu / اردو' },
  { code: 'hi', label: 'Hindi / हिंदी' },
  { code: 'es', label: 'Spanish' },
  { code: 'ar', label: 'Arabic' },
]

export default function AIStoryPage() {
  const { data: channels } = usePoll<Channel[]>('/api/channels', 10000)
  const [channelId, setChannelId] = useState<number>(1)
  const [prompt, setPrompt] = useState('')
  const [genre, setGenre] = useState('kids_fairy_tale')
  const [sceneCount, setSceneCount] = useState(5)
  const [targetSeconds, setTargetSeconds] = useState(60)
  const [language, setLanguage] = useState('en')
  const [autoUpload, setAutoUpload] = useState(true)
  const [busy, setBusy] = useState(false)
  const [results, setResults] = useState<any>(null)
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null)

  const generate = async () => {
    if (!prompt.trim()) {
      setMsg({ ok: false, text: 'Please enter a story idea' })
      return
    }
    setBusy(true)
    setMsg(null)
    setResults(null)
    try {
      const r = await api.post<any>('/api/v21/story/generate', {
        prompt: prompt.trim(),
        genre,
        scene_count: sceneCount,
        target_seconds: targetSeconds,
        language,
        auto_upload: autoUpload,
        channel_id: channelId,
      })
      setResults(r)
      if (r.success) {
        const title = r.story?.title || 'Story'
        const uploaded = r.upload?.awaiting_review
          ? ' · Awaiting human approval before live upload'
          : r.upload?.success ? ' · Uploaded to YouTube!' : ''
        setMsg({ ok: true, text: `✓ Story video created: "${title}"${uploaded}` })
      } else {
        setMsg({ ok: false, text: r.reason || 'Generation failed' })
      }
    } catch (e) {
      setMsg({ ok: false, text: e instanceof Error ? e.message : String(e) })
    } finally {
      setBusy(false)
    }
  }

  return (
    <div>
      <PageHeader title="🤖 AI Story Video Generator">
        <select className="input !w-48" value={channelId}
          onChange={(e) => setChannelId(Number(e.target.value))}>
          {(channels ?? []).map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
        </select>
      </PageHeader>

      {msg && (
        <div className={`mb-4 rounded-lg px-4 py-2.5 text-sm ${
          msg.ok ? 'bg-emerald-500/15 text-emerald-300' : 'bg-rose-500/15 text-rose-300'
        }`}>{msg.text}</div>
      )}

      <div className="card mb-6">
        <div className="mb-3 text-xs font-semibold uppercase tracking-wider text-zinc-500">
          Create a viral AI story video (100% free — no API key needed for images)
        </div>

        <div className="space-y-4">
          {/* Story prompt */}
          <div>
            <label className="label">Story idea / prompt</label>
            <textarea className="input min-h-20" value={prompt}
              onChange={(e) => setPrompt(e.target.value)}
              placeholder="e.g. A brave little rabbit who saves the forest from a fire..." />
          </div>

          {/* Genre selection */}
          <div>
            <label className="label">Story genre</label>
            <div className="grid gap-2 md:grid-cols-4">
              {GENRES.map((g) => (
                <button key={g.value} type="button"
                  onClick={() => setGenre(g.value)}
                  className={`rounded-lg border px-3 py-2 text-left transition-colors ${
                    genre === g.value
                      ? 'border-phoenix-400 bg-phoenix-500/15 text-phoenix-200'
                      : 'border-ink-600 bg-ink-800 text-zinc-400 hover:border-ink-500'
                  }`}>
                  <div className="text-sm font-semibold">{g.label}</div>
                  <div className="mt-0.5 text-[10px] text-zinc-500">{g.desc}</div>
                </button>
              ))}
            </div>
          </div>

          {/* Settings */}
          <div className="grid gap-4 md:grid-cols-3">
            <div>
              <label className="label">Scene count (images)</label>
              <select className="input" value={sceneCount}
                onChange={(e) => setSceneCount(Number(e.target.value))}>
                {[3, 4, 5, 6, 7, 8, 10, 12].map((n) => <option key={n} value={n}>{n} scenes</option>)}
              </select>
            </div>
            <div>
              <label className="label">Target video length</label>
              <select className="input" value={targetSeconds}
                onChange={(e) => setTargetSeconds(Number(e.target.value))}>
                {[30, 45, 60, 90, 120, 180, 300].map((s) => (
                  <option key={s} value={s}>{s < 60 ? `${s}s` : `${Math.floor(s/60)}m${s%60 ? ` ${s%60}s` : ''}`}</option>
                ))}
              </select>
            </div>
            <div>
              <label className="label">Language</label>
              <select className="input" value={language}
                onChange={(e) => setLanguage(e.target.value)}>
                {LANGUAGES.map((l) => <option key={l.code} value={l.code}>{l.label}</option>)}
              </select>
            </div>
          </div>

          {/* Auto-upload toggle */}
          <label className="flex cursor-pointer items-center gap-3 rounded-lg bg-ink-800 px-3 py-2.5">
            <div>
              <div className="text-sm font-medium text-zinc-200">🚀 Auto-upload to YouTube</div>
              <div className="mt-0.5 text-[11px] text-zinc-500">
                Auto-generates title + tags + description, uploads, runs copyright check, publishes
              </div>
            </div>
            <button type="button" onClick={() => setAutoUpload(!autoUpload)}
              className={`relative h-6 w-11 flex-shrink-0 rounded-full transition-colors ${
                autoUpload ? 'bg-phoenix-500' : 'bg-ink-600'}`}>
              <span className={`absolute top-0.5 h-5 w-5 rounded-full bg-white shadow transition-transform ${
                autoUpload ? 'translate-x-5' : 'translate-x-0.5'}`} />
            </button>
          </label>

          <button className="btn-primary w-full" onClick={generate} disabled={busy}>
            {busy ? '⏳ Generating story → AI images → voice → video → upload...' : '🤖 Generate AI Story Video'}
          </button>
        </div>
      </div>

      {/* How it works */}
      <div className="card mb-6">
        <div className="mb-3 text-xs font-semibold uppercase tracking-wider text-zinc-500">
          How it works (100% free)
        </div>
        <div className="grid gap-3 md:grid-cols-5">
          {[
            { step: '1', icon: '✍️', title: 'LLM writes story', desc: 'GroK/Gemini/OpenRouter writes an original scene-by-scene story' },
            { step: '2', icon: '🎨', title: 'AI images', desc: 'Pollinations AI generates illustrations (free, no key)' },
            { step: '3', icon: '🎤', title: 'Voice narration', desc: 'Edge-TTS narrates each scene in your chosen language' },
            { step: '4', icon: '🎬', title: 'Video assembly', desc: 'FFmpeg assembles images + voice + music with Ken Burns zoom' },
            { step: '5', icon: '🚀', title: 'Auto-upload', desc: 'Title + tags + description auto-generated, uploaded to YouTube' },
          ].map((s) => (
            <div key={s.step} className="rounded-lg bg-ink-800 p-3">
              <div className="text-2xl">{s.icon}</div>
              <div className="mt-2 text-sm font-semibold text-zinc-200">{s.title}</div>
              <div className="mt-1 text-[10px] text-zinc-500">{s.desc}</div>
            </div>
          ))}
        </div>
      </div>

      {/* Results */}
      {results && (
        <div className="card">
          <div className="mb-4 text-xs font-semibold uppercase tracking-wider text-zinc-500">
            Results
          </div>
          {results.story && (
            <div className="mb-3 rounded-lg bg-ink-800 px-3 py-2">
              <div className="text-sm font-semibold text-phoenix-300">{results.story.title}</div>
              <div className="mt-1 text-[11px] text-zinc-500">
                {results.story.scenes?.length || 0} scenes · {results.duration?.toFixed(1) || 0}s · genre: {results.story.genre}
              </div>
            </div>
          )}
          {results.upload && (
            <div className="rounded-lg bg-ink-800 px-3 py-2">
              {results.upload.awaiting_review ? (
                <span className="text-amber-300">Awaiting human approval before live upload.</span>
              ) : results.upload.success ? (
                <div className="text-sm">
                  <span className="text-emerald-400">✓ Uploaded: {results.upload.title}</span>
                  {results.upload.url && (
                    <a href={results.upload.url} target="_blank" rel="noreferrer"
                      className="ml-2 text-phoenix-400 hover:underline">Watch ↗</a>
                  )}
                </div>
              ) : (
                <span className="text-rose-400">Upload failed: {results.upload.reason}</span>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  )
}
