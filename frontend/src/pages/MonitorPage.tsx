import { useState } from 'react'
import { PageHeader } from '../components/Layout'
import StatCard from '../components/StatCard'
import { api, fmt, timeAgo, usePoll } from '../lib/api'
import type { Channel, LearnedInsight, MonitorStats, TrendingVideo } from '../lib/types'

const NICHES = ['technology', 'finance', 'health', 'space', 'history', 'science',
  'education', 'entertainment', 'gaming', 'lifestyle', 'news', 'music',
  'travel', 'food', 'fitness', 'sports', 'automotive', 'diy', 'art',
  'business', 'psychology', 'philosophy', 'politics', 'fashion']

interface ResearchTopic {
  topic: string
  niche: string
  score: number
  score_basis?: string
  source?: string
  data_quality?: string
  angle?: string
  source_views?: number
}

interface ResearchReport {
  available: boolean
  date?: string
  source: string
  winning_niche?: string
  topics: ResearchTopic[]
  created_at?: string | null
}

function fmtDuration(s: number): string {
  if (!s) return '—'
  const m = Math.floor(s / 60)
  const sec = Math.round(s % 60)
  if (m === 0) return `${sec}s`
  if (m < 60) return `${m}m ${sec}s`
  return `${Math.floor(m / 60)}h ${m % 60}m`
}

export default function MonitorPage() {
  const { data: channels } = usePoll<Channel[]>('/api/channels', 10000)
  const [channelId, setChannelId] = useState<number | null>(null)
  const cid = channelId ?? channels?.[0]?.id ?? 1

  const { data: stats } = usePoll<MonitorStats>(`/api/monitor/stats/${cid}`, 10000)
  const { data: trending, error: tErr } = usePoll<TrendingVideo[]>(
    `/api/monitor/trending/${cid}?limit=50`, 15000)
  const { data: insights } = usePoll<LearnedInsight[]>(
    `/api/monitor/insights/${cid}?limit=100`, 15000)
  const { data: researchReport } = usePoll<ResearchReport>(
    `/api/monitor/research/latest/${cid}`, 15000)

  const [query, setQuery] = useState('')
  const [pickedNiches, setPickedNiches] = useState<string[]>(['technology'])
  const [region, setRegion] = useState('US')
  const [minViews, setMinViews] = useState(2_000_000)
  const [maxResults, setMaxResults] = useState(20)
  const [learn, setLearn] = useState(true)
  const [busy, setBusy] = useState(false)
  const [researchBusy, setResearchBusy] = useState(false)
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null)

  const toggleNiche = (n: string) => {
    setPickedNiches((cur) => cur.includes(n) ? cur.filter((x) => x !== n) : [...cur, n])
  }

  const runSearch = async () => {
    setBusy(true)
    setMsg(null)
    try {
      const r = await api.post<{
        found: number
        stored: number
        insights_extracted: number
        top_video?: { title: string; view_count: number } | null
      }>('/api/monitor/search', {
        channel_id: cid,
        query: query.trim() || null,
        niches: pickedNiches,
        region_code: region,
        min_views: minViews,
        max_results: maxResults,
        learn,
      })
      setMsg({
        ok: true,
        text: `Found ${r.found} · stored ${r.stored} · extracted ${r.insights_extracted} insights` +
          (r.top_video ? ` · top: "${r.top_video.title.slice(0, 60)}" (${fmt(r.top_video.view_count)} views)` : ''),
      })
    } catch (e) {
      setMsg({ ok: false, text: e instanceof Error ? e.message : String(e) })
    } finally {
      setBusy(false)
    }
  }

  const runTopicResearch = async () => {
    setResearchBusy(true)
    setMsg(null)
    try {
      const r = await api.post<ResearchReport>(`/api/monitor/research/${cid}?limit=10`)
      setMsg({ ok: true, text: `Topic research complete: ${r.topics.length} suggestions · source ${r.source} · winner ${r.winning_niche ?? '—'}` })
    } catch (e) {
      setMsg({ ok: false, text: e instanceof Error ? e.message : String(e) })
    } finally {
      setResearchBusy(false)
    }
  }

  const extractNow = async () => {
    setBusy(true)
    setMsg(null)
    try {
      const r = await api.post<{ extracted: number }>(`/api/monitor/extract/${cid}?max_videos=20`)
      setMsg({ ok: true, text: `Extracted ${r.extracted} new insights` })
    } catch (e) {
      setMsg({ ok: false, text: e instanceof Error ? e.message : String(e) })
    } finally {
      setBusy(false)
    }
  }

  // Group insights by type for display.
  const byType: Record<string, LearnedInsight[]> = {}
  for (const ins of insights ?? []) {
    byType[ins.insight_type] = byType[ins.insight_type] || []
    byType[ins.insight_type].push(ins)
  }

  return (
    <div>
      <PageHeader title="YouTube Monitor">
        <select className="input !w-56" value={cid}
          onChange={(e) => setChannelId(Number(e.target.value))}>
          {(channels ?? []).map((c) => (
            <option key={c.id} value={c.id}>{c.name}</option>
          ))}
        </select>
      </PageHeader>

      {/* Stats cards */}
      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        <StatCard label="Trending videos cached" value={String(stats?.trending_count ?? 0)} icon="📈" />
        <StatCard label="Learned insights" value={String(stats?.insights_count ?? 0)} icon="🧠" />
        <StatCard label="Min views threshold" value={fmt(stats?.min_views ?? 0)} icon="🎯" />
        <StatCard label="Daily quota" value={String(stats?.daily_quota ?? 0)} icon="⏱" />
      </div>

      {msg && (
        <div className={`mt-4 rounded-lg px-4 py-2.5 text-sm ${
          msg.ok ? 'bg-emerald-500/15 text-emerald-300' : 'bg-rose-500/15 text-rose-300'
        }`}>
          {msg.text}
        </div>
      )}

      {/* Automatic topic research */}
      <div className="card mt-6 border-emerald-200/15 bg-emerald-300/[0.035]">
        <div className="mb-4 flex items-center justify-between gap-3">
          <div>
            <div className="text-xs font-semibold uppercase tracking-wider text-emerald-100/70">Automatic topic research</div>
            <div className="mt-1 text-xs text-white/45">Real signals are preferred; fallback suggestions are explicitly labelled and are never shown as live trend data.</div>
          </div>
          <button className="btn-primary" onClick={runTopicResearch} disabled={researchBusy}>{researchBusy ? 'researching…' : 'research topics now'}</button>
        </div>
        <div className="mb-3 flex flex-wrap gap-2 text-[10px]">
          <span className="glass-chip text-emerald-100">source: {researchReport?.source ?? 'none yet'}</span>
          {researchReport?.winning_niche && <span className="glass-chip text-fuchsia-100">winning niche: {researchReport.winning_niche}</span>}
          {researchReport?.date && <span className="glass-chip text-zinc-300">date: {researchReport.date}</span>}
        </div>
        <div className="grid gap-2 md:grid-cols-2">
          {(researchReport?.topics ?? []).slice(0, 6).map((item, index) => (
            <div className="rounded-xl border border-white/8 bg-black/15 p-3" key={`${item.topic}-${index}`}>
              <div className="flex items-start justify-between gap-3"><div className="text-sm text-zinc-200">{item.topic}</div><span className="text-[10px] text-emerald-200">{item.source ?? 'unknown'}</span></div>
              <div className="mt-1 text-[10px] text-zinc-500">score {item.score} · {item.data_quality ?? 'unlabelled'} · {item.score_basis ?? 'not specified'}</div>
              {item.angle && <div className="mt-2 text-[11px] leading-relaxed text-white/45">{item.angle}</div>}
            </div>
          ))}
          {(researchReport?.topics ?? []).length === 0 && <div className="py-5 text-center text-xs text-zinc-600 md:col-span-2">No research report yet. Click “research topics now”; connect YouTube/API providers for live signals.</div>}
        </div>
      </div>

      {/* Search panel */}
      <div className="card mt-6">
        <div className="mb-4 text-xs font-semibold uppercase tracking-wider text-zinc-500">
          Search YouTube for top videos in a niche
        </div>
        <div className="grid gap-4 lg:grid-cols-3">
          <div className="lg:col-span-2">
            <label className="label">Free-text query (optional)</label>
            <input className="input" value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder='e.g. "history of roman empire" — overrides niches if set' />
          </div>
          <div>
            <label className="label">Region</label>
            <select className="input" value={region}
              onChange={(e) => setRegion(e.target.value)}>
              {['US', 'GB', 'IN', 'PK', 'AE', 'CA', 'AU', 'DE', 'FR',
                'BR', 'JP', 'KR', 'ID', 'TR', 'SA'].map((r) =>
                <option key={r} value={r}>{r}</option>)}
            </select>
          </div>
        </div>

        <div className="mt-4">
          <label className="label">Niches (when query is empty)</label>
          <div className="flex flex-wrap gap-1.5">
            {NICHES.map((n) => (
              <button key={n} type="button" onClick={() => toggleNiche(n)}
                className={`rounded-full px-3 py-1 text-xs font-semibold transition-colors ${
                  pickedNiches.includes(n)
                    ? 'bg-phoenix-500/30 text-phoenix-200 ring-1 ring-phoenix-400'
                    : 'bg-ink-700 text-zinc-400 hover:bg-ink-600 hover:text-zinc-200'
                }`}>
                {n}
              </button>
            ))}
          </div>
        </div>

        <div className="mt-4 grid gap-4 md:grid-cols-3">
          <div>
            <label className="label">Min views</label>
            <select className="input" value={minViews}
              onChange={(e) => setMinViews(Number(e.target.value))}>
              <option value={1_000_000}>1M+ views</option>
              <option value={2_000_000}>2M+ views</option>
              <option value={5_000_000}>5M+ views</option>
              <option value={10_000_000}>10M+ views</option>
              <option value={50_000_000}>50M+ views</option>
              <option value={100_000_000}>100M+ views</option>
            </select>
          </div>
          <div>
            <label className="label">Max results per niche</label>
            <select className="input" value={maxResults}
              onChange={(e) => setMaxResults(Number(e.target.value))}>
              {[5, 10, 20, 30, 50].map((n) => <option key={n} value={n}>{n}</option>)}
            </select>
          </div>
          <div>
            <label className="label">Learn from results</label>
            <button type="button" onClick={() => setLearn((v) => !v)}
              className={`relative h-10 w-full rounded-lg px-3 text-sm font-medium transition-colors ${
                learn ? 'bg-phoenix-500/30 text-phoenix-200' : 'bg-ink-700 text-zinc-400'
              }`}>
              {learn ? '✓ Extract insights (hooks, tags, patterns)' : 'Off — just fetch metadata'}
            </button>
          </div>
        </div>

        <div className="mt-4 flex gap-2">
          <button className="btn-primary" onClick={runSearch} disabled={busy}>
            {busy ? 'searching…' : '🔍 Search & Learn'}
          </button>
          <button className="btn-ghost" onClick={extractNow} disabled={busy}>
            🧠 re-extract insights
          </button>
        </div>
      </div>

      {/* Trending videos table */}
      <div className="card mt-6">
        <div className="mb-4 flex items-center justify-between">
          <div className="text-xs font-semibold uppercase tracking-wider text-zinc-500">
            Trending videos ({trending?.length ?? 0})
          </div>
        </div>
        {tErr && (
          <div className="rounded-lg bg-rose-500/10 px-3 py-2 text-xs text-rose-300">
            {tErr}
          </div>
        )}
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-xs uppercase tracking-wider text-zinc-500">
                <th className="pb-2 pr-4">Video</th>
                <th className="pb-2 pr-4">Niche</th>
                <th className="pb-2 pr-4 text-right">Views</th>
                <th className="pb-2 pr-4 text-right">Likes</th>
                <th className="pb-2 pr-4 text-right">Duration</th>
                <th className="pb-2 text-right">Analyzed</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-ink-700">
              {(trending ?? []).map((v) => (
                <tr key={v.id} className="hover:bg-ink-800">
                  <td className="max-w-md py-2.5 pr-4">
                    <div className="flex items-start gap-2">
                      {v.thumbnail && (
                        <img src={v.thumbnail} alt="" className="h-12 w-20 flex-shrink-0 rounded object-cover"
                          onError={(e) => { (e.target as HTMLImageElement).style.display = 'none' }} />
                      )}
                      <div className="min-w-0">
                        <a href={`https://youtu.be/${v.yt_video_id}`} target="_blank" rel="noreferrer"
                          className="block truncate text-zinc-200 hover:text-phoenix-300">
                          {v.title}
                        </a>
                        <div className="text-[11px] text-zinc-500">{v.channel_title}</div>
                      </div>
                    </div>
                  </td>
                  <td className="py-2.5 pr-4 text-zinc-400">{v.niche}</td>
                  <td className="py-2.5 pr-4 text-right font-mono text-phoenix-300">{fmt(v.view_count)}</td>
                  <td className="py-2.5 pr-4 text-right font-mono text-emerald-400">{fmt(v.like_count)}</td>
                  <td className="py-2.5 pr-4 text-right font-mono text-zinc-400">
                    {fmtDuration(v.duration_seconds)}
                  </td>
                  <td className="py-2.5 text-right">
                    {v.analyzed
                      ? <span className="text-[10px] font-semibold text-emerald-400">✓</span>
                      : <span className="text-[10px] font-semibold text-amber-400">pending</span>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {(trending ?? []).length === 0 && (
            <div className="py-12 text-center text-xs text-zinc-600">
              No trending videos cached yet. Pick a niche above and hit "Search & Learn" —
              the monitor will pull top YouTube videos with {fmt(minViews)}+ views and learn from them.
            </div>
          )}
        </div>
      </div>

      {/* Learned insights by type */}
      <div className="mt-6 grid gap-4 lg:grid-cols-2">
        {(['hook', 'title_pattern', 'tag_cluster', 'description_pattern',
          'duration_band', 'takeaway'] as const).map((itype) => {
          const rows = byType[itype] || []
          if (rows.length === 0) return null
          return (
            <div key={itype} className="card">
              <div className="mb-3 flex items-center justify-between">
                <div className="text-xs font-semibold uppercase tracking-wider text-phoenix-400">
                  {itype.replace(/_/g, ' ')}s ({rows.length})
                </div>
              </div>
              <div className="space-y-2">
                {rows.slice(0, 8).map((r) => (
                  <div key={r.id} className="rounded-lg bg-ink-800 px-3 py-2 text-xs">
                    <div className="text-zinc-200">{r.content}</div>
                    <div className="mt-1 flex items-center justify-between text-[10px] text-zinc-500">
                      <span>niche: {r.niche}</span>
                      <span>score: {r.score.toFixed(1)} · {timeAgo(r.created_at)}</span>
                    </div>
                  </div>
                ))}
                {rows.length > 8 && (
                  <div className="text-center text-[10px] text-zinc-600">
                    +{rows.length - 8} more
                  </div>
                )}
              </div>
            </div>
          )
        })}
        {(insights ?? []).length === 0 && (
          <div className="card py-12 text-center text-xs text-zinc-600 lg:col-span-2">
            No insights extracted yet. Run a monitor search with "Learn from results" enabled —
            the LLM will pull hooks, tag clusters, title patterns and takeaways from each top video.
          </div>
        )}
      </div>
    </div>
  )
}
