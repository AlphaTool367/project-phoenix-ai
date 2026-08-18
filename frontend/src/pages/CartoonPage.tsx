import { useState } from 'react'
import { PageHeader } from '../components/Layout'
import { api, usePoll, fmt } from '../lib/api'
import type { Channel } from '../lib/types'

interface SearchResult {
  title: string
  url: string
  id: string
  duration: number
  channel: string
  view_count: number
  thumbnail: string
}

interface UploadResult {
  index: number
  success?: boolean
  skipped?: boolean
  awaiting_review?: boolean
  title?: string
  yt_video_id?: string
  url?: string
  reason?: string
}

export default function CartoonPage() {
  const { data: channels } = usePoll<Channel[]>('/api/channels', 10000)
  const [channelId, setChannelId] = useState<number>(1)
  const [searchQuery, setSearchQuery] = useState('')
  const [searchResults, setSearchResults] = useState<SearchResult[]>([])
  const [searching, setSearching] = useState(false)
  const [processing, setProcessing] = useState(false)
  const [downloadUrl, setDownloadUrl] = useState('')
  const [quality, setQuality] = useState('1080p')
  const [maxShorts, setMaxShorts] = useState(3)
  const [shortDuration, setShortDuration] = useState(60)
  const [autoUpload, setAutoUpload] = useState(true)
  const [results, setResults] = useState<any>(null)
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null)

  const search = async () => {
    if (!searchQuery.trim()) return
    setSearching(true)
    setMsg(null)
    try {
      const r = await api.post<{ results: SearchResult[]; count: number }>(
        '/api/v21/cartoon/search', { query: searchQuery, max_results: 10 })
      setSearchResults(r.results)
      setMsg({ ok: true, text: `${r.count} cartoons found` })
    } catch (e) {
      setMsg({ ok: false, text: e instanceof Error ? e.message : String(e) })
    } finally {
      setSearching(false)
    }
  }

  const useUrl = (url: string) => {
    setDownloadUrl(url)
    window.scrollTo({ top: 0, behavior: 'smooth' })
  }

  const runFullFlow = async () => {
    if (!downloadUrl.trim()) {
      setMsg({ ok: false, text: 'Please enter a YouTube URL or search above' })
      return
    }
    setProcessing(true)
    setMsg(null)
    setResults(null)
    try {
      const r = await api.post<any>(
        `/api/v21/cartoon/full-flow?url=${encodeURIComponent(downloadUrl)}&channel_id=${channelId}&max_shorts=${maxShorts}&short_duration=${shortDuration}&quality=${quality}&auto_upload=${autoUpload}`)
      setResults(r)
      const uploaded = r.uploaded || 0
      const total = r.shorts?.length || 0
      const awaiting = (r.uploads || []).filter((u: UploadResult) => u.awaiting_review).length
      setMsg({
        ok: true,
        text: `Done! ${total} Shorts created, ${uploaded} uploaded to YouTube${awaiting ? `, ${awaiting} awaiting human approval` : ''}.`,
      })
    } catch (e) {
      setMsg({ ok: false, text: e instanceof Error ? e.message : String(e) })
    } finally {
      setProcessing(false)
    }
  }

  return (
    <div>
      <PageHeader title="🎬 Cartoon Downloader → Shorts">
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

      {/* Step 1: Search or paste URL */}
      <div className="card mb-6">
        <div className="mb-3 text-xs font-semibold uppercase tracking-wider text-zinc-500">
          Step 1: Find a cartoon
        </div>
        <div className="flex flex-wrap gap-3">
          <input className="input min-w-64 flex-1" value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            placeholder='Search: "Tom and Jerry", "Peppa Pig", "Mickey Mouse"...'
            onKeyDown={(e) => e.key === 'Enter' && search()} />
          <button className="btn-ghost" onClick={search} disabled={searching}>
            {searching ? 'searching…' : '🔍 Search YouTube'}
          </button>
        </div>

        {searchResults.length > 0 && (
          <div className="mt-4 grid gap-3 md:grid-cols-2">
            {searchResults.map((r) => (
              <div key={r.id} className="flex gap-3 rounded-lg bg-ink-800 p-3">
                {r.thumbnail && (
                  <img src={r.thumbnail} alt="" className="h-16 w-28 rounded object-cover"
                    onError={(e) => { (e.target as HTMLImageElement).style.display = 'none' }} />
                )}
                <div className="min-w-0 flex-1">
                  <div className="truncate text-sm font-medium text-zinc-200">{r.title}</div>
                  <div className="mt-1 text-[11px] text-zinc-500">
                    {r.channel} · {fmt(r.view_count)} views · {r.duration ? `${Math.round(r.duration)}s` : '—'}
                  </div>
                  <button className="mt-2 rounded bg-phoenix-500/20 px-2 py-1 text-[10px] font-semibold text-phoenix-300 hover:bg-phoenix-500/30"
                    onClick={() => useUrl(r.url)}>
                    Use this →
                  </button>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Step 2: Download + Process + Upload */}
      <div className="card mb-6">
        <div className="mb-3 text-xs font-semibold uppercase tracking-wider text-zinc-500">
          Step 2: Download → Clip → Modify → Upload (all automatic)
        </div>
        <div className="space-y-4">
          <div>
            <label className="label">YouTube URL (paste from search or manually)</label>
            <input className="input" value={downloadUrl}
              onChange={(e) => setDownloadUrl(e.target.value)}
              placeholder="https://www.youtube.com/watch?v=..." />
          </div>

          <div className="grid gap-4 md:grid-cols-3">
            <div>
              <label className="label">Video quality</label>
              <select className="input" value={quality} onChange={(e) => setQuality(e.target.value)}>
                <option value="1080p">Full HD (1080p)</option>
                <option value="720p">HD (720p)</option>
                <option value="480p">SD (480p)</option>
              </select>
            </div>
            <div>
              <label className="label">Number of Shorts</label>
              <select className="input" value={maxShorts} onChange={(e) => setMaxShorts(Number(e.target.value))}>
                {[1, 2, 3, 4, 5].map((n) => <option key={n} value={n}>{n} Shorts</option>)}
              </select>
            </div>
            <div>
              <label className="label">Short duration (seconds)</label>
              <select className="input" value={shortDuration} onChange={(e) => setShortDuration(Number(e.target.value))}>
                {[30, 45, 60, 90, 120].map((s) => <option key={s} value={s}>{s}s</option>)}
              </select>
            </div>
          </div>

          <label className="flex cursor-pointer items-center gap-3 rounded-lg bg-ink-800 px-3 py-2.5">
            <div>
              <div className="text-sm font-medium text-zinc-200">🚀 Auto-upload to YouTube</div>
              <div className="mt-0.5 text-[11px] text-zinc-500">
                Automatically generates title + tags + description, uploads, runs copyright check, and publishes
              </div>
            </div>
            <button type="button" onClick={() => setAutoUpload(!autoUpload)}
              className={`relative h-6 w-11 flex-shrink-0 rounded-full transition-colors ${
                autoUpload ? 'bg-phoenix-500' : 'bg-ink-600'}`}>
              <span className={`absolute top-0.5 h-5 w-5 rounded-full bg-white shadow transition-transform ${
                autoUpload ? 'translate-x-5' : 'translate-x-0.5'}`} />
            </button>
          </label>

          <button className="btn-primary w-full" onClick={runFullFlow} disabled={processing}>
            {processing ? '⏳ Processing... (download → clip → modify → upload)' : '🚀 Start Full Flow'}
          </button>
        </div>
      </div>

      {/* Results */}
      {results && (
        <div className="card">
          <div className="mb-4 text-xs font-semibold uppercase tracking-wider text-zinc-500">
            Results
          </div>
          {results.download && (
            <div className="mb-3 rounded-lg bg-ink-800 px-3 py-2 text-sm">
              <strong className="text-zinc-300">Downloaded:</strong> {results.download.title || 'unknown'}
              {' '}({results.download.duration ? `${Math.round(results.download.duration)}s` : '—'})
            </div>
          )}
          {results.shorts && results.shorts.length > 0 && (
            <div className="space-y-2">
              {results.shorts.map((s: any, i: number) => (
                <div key={i} className="rounded-lg bg-ink-800 px-3 py-2 text-sm">
                  <div className="flex items-center justify-between">
                    <span className="text-zinc-200">Short #{i + 1}</span>
                    <span className={`text-[10px] font-semibold ${
                      s.clean ? 'text-emerald-400' : 'text-rose-400'}`}>
                      {s.clean ? '✓ copyright clean' : '⚠ copyright flagged'}
                    </span>
                  </div>
                  <div className="mt-1 text-[11px] text-zinc-500">
                    {s.start?.toFixed(1)}s - {s.end?.toFixed(1)}s · {s.duration?.toFixed(1)}s
                  </div>
                </div>
              ))}
            </div>
          )}
          {results.uploads && results.uploads.length > 0 && (
            <div className="mt-4 space-y-2">
              <div className="text-xs font-semibold uppercase tracking-wider text-phoenix-400">
                Upload Results
              </div>
              {results.uploads.map((u: UploadResult, i: number) => (
                <div key={i} className="rounded-lg bg-ink-800 px-3 py-2 text-sm">
                  {u.skipped ? (
                    <span className="text-amber-400">⚠ Short {u.index} skipped (copyright)</span>
                  ) : u.awaiting_review ? (
                    <span className="text-amber-300">⏳ Short {u.index} awaiting human approval before live upload</span>
                  ) : u.success ? (
                    <div>
                      <span className="text-emerald-400">✓ Uploaded: {u.title}</span>
                      {u.url && <a href={u.url} target="_blank" rel="noreferrer"
                        className="ml-2 text-phoenix-400 hover:underline">Watch ↗</a>}
                    </div>
                  ) : (
                    <span className="text-rose-400">✗ Short {u.index} failed: {u.reason}</span>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  )
}
