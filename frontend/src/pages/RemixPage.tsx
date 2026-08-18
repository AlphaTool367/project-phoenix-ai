import { useState } from 'react'
import { PageHeader } from '../components/Layout'
import { api, usePoll } from '../lib/api'
import type { Channel } from '../lib/types'

export default function RemixPage() {
  const { data: channels } = usePoll<Channel[]>('/api/channels', 10000)
  const [channelId, setChannelId] = useState<number>(1)
  const [uploadMsg, setUploadMsg] = useState('')
  const [filePath, setFilePath] = useState('')
  const [language, setLanguage] = useState('en')
  const [autoUpload, setAutoUpload] = useState(true)
  const [busy, setBusy] = useState(false)
  const [results, setResults] = useState<any>(null)
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null)

  const uploadFile = async (file: File) => {
    setUploadMsg('Uploading...')
    const formData = new FormData()
    formData.append('file', file)
    try {
      const r = await fetch('/api/v21/remix/upload', { method: 'POST', body: formData })
      if (!r.ok) throw new Error(`Upload failed: ${r.status}`)
      const data = await r.json()
      setFilePath(data.path)
      setUploadMsg(`✓ Uploaded: ${file.name} (${data.size_mb} MB)`)
    } catch (e) {
      setUploadMsg(`✗ ${e instanceof Error ? e.message : String(e)}`)
    }
  }

  const remix = async () => {
    if (!filePath) {
      setMsg({ ok: false, text: 'Please upload a video first' })
      return
    }
    setBusy(true)
    setMsg(null)
    setResults(null)
    try {
      const r = await api.post<any>('/api/v21/remix/create', {
        source_path: filePath,
        language,
        auto_upload: autoUpload,
        channel_id: channelId,
      })
      setResults(r)
      if (r.success) {
        const title = r.story?.title || 'Remixed video'
        setMsg({ ok: true, text: `✓ Remixed video created: "${title}"` })
      } else {
        setMsg({ ok: false, text: r.reason || 'Remix failed' })
      }
    } catch (e) {
      setMsg({ ok: false, text: e instanceof Error ? e.message : String(e) })
    } finally {
      setBusy(false)
    }
  }

  return (
    <div>
      <PageHeader title="🎬 Video Remix">
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
          Upload a viral video → AI creates a similar but original video
        </div>

        <div className="space-y-4">
          {/* Upload */}
          <div>
            <label className="label">Upload reference video</label>
            <input type="file" accept="video/*" className="input"
              onChange={(e) => {
                const f = e.target.files?.[0]
                if (f) uploadFile(f)
              }} />
            {uploadMsg && <div className="mt-1 text-[11px] text-zinc-400">{uploadMsg}</div>}
          </div>

          {filePath && (
            <div className="rounded-lg bg-emerald-500/10 px-3 py-2 text-sm text-emerald-300">
              ✓ File ready: {filePath}
            </div>
          )}

          {/* Settings */}
          <div className="grid gap-4 md:grid-cols-2">
            <div>
              <label className="label">Language</label>
              <select className="input" value={language}
                onChange={(e) => setLanguage(e.target.value)}>
                <option value="en">English</option>
                <option value="ur">Urdu / اردو</option>
                <option value="hi">Hindi / हिंदी</option>
                <option value="es">Spanish</option>
              </select>
            </div>
            <div>
              <label className="label">Auto-upload</label>
              <button type="button" onClick={() => setAutoUpload(!autoUpload)}
                className={`relative h-10 w-full rounded-lg px-3 text-sm font-medium transition-colors ${
                  autoUpload ? 'bg-phoenix-500/30 text-phoenix-200' : 'bg-ink-700 text-zinc-400'}`}>
                {autoUpload ? '✓ Auto-upload ON' : 'Auto-upload OFF'}
              </button>
            </div>
          </div>

          <button className="btn-primary w-full" onClick={remix} disabled={busy || !filePath}>
            {busy ? '⏳ Analyzing → Creating new story → Generating video...' : '🎬 Remix Video'}
          </button>
        </div>
      </div>

      {/* How it works */}
      <div className="card mb-6">
        <div className="mb-3 text-xs font-semibold uppercase tracking-wider text-zinc-500">
          How remixing works
        </div>
        <div className="grid gap-3 md:grid-cols-4">
          {[
            { step: '1', icon: '📝', title: 'Transcript', desc: 'Whisper extracts the video transcript (optional)' },
            { step: '2', icon: '🔍', title: 'Analyze', desc: 'LLM analyzes topic, genre, tone, scene structure' },
            { step: '3', icon: '✨', title: 'New story', desc: 'LLM writes a completely new but similar story' },
            { step: '4', icon: '🎬', title: 'Generate + upload', desc: 'AI images + voice + video → auto-upload' },
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
            Remix Results
          </div>
          {!results.success && results.reason && (
            <div className="mb-3 rounded-lg bg-amber-500/10 px-3 py-2 text-sm text-amber-200">
              {results.reason}{results.next_step ? ` ${results.next_step}` : ''}
            </div>
          )}
          {results.analysis && (
            <div className="mb-3 rounded-lg bg-ink-800 px-3 py-2 text-sm">
              <div className="text-zinc-300">
                <strong>Original:</strong> {results.analysis.topic} ({results.analysis.genre})
              </div>
            </div>
          )}
          {results.upload && (
            <div className="mb-3 rounded-lg bg-ink-800 px-3 py-2 text-sm">
              {results.upload.awaiting_review ? (
                <span className="text-amber-300">Awaiting human approval before live upload.</span>
              ) : results.upload.success ? (
                <span className="text-emerald-400">✓ Uploaded/remix upload accepted</span>
              ) : (
                <span className="text-rose-400">Upload failed: {results.upload.reason}</span>
              )}
            </div>
          )}
          {results.story && (
            <div className="mb-3 rounded-lg bg-ink-800 px-3 py-2 text-sm">
              <div className="font-semibold text-phoenix-300">{results.story.title}</div>
              <div className="mt-1 text-[11px] text-zinc-500">
                {results.story.scenes?.length || 0} scenes · {results.duration?.toFixed(1) || 0}s
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
