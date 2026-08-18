import { useState } from 'react'
import {
  Area, AreaChart, CartesianGrid, Legend, ResponsiveContainer, Tooltip,
  XAxis, YAxis,
} from 'recharts'
import { PageHeader } from '../components/Layout'
import StatCard from '../components/StatCard'
import { api, fmt, usePoll } from '../lib/api'
import type { AnalyticsSummary, Channel, LeaderboardRow } from '../lib/types'

interface TimeseriesPoint {
  ts: string
  video_id: number
  views: number
  retention_pct: number
  ctr_pct: number
  subs_gained: number
}

export default function AnalyticsPage() {
  const { data: channels } = usePoll<Channel[]>('/api/channels', 10000)
  const [channelId, setChannelId] = useState<number | null>(null)
  const cid = channelId ?? channels?.[0]?.id ?? 1

  // Use the realtime endpoint so the dashboard shows live YouTube stats.
  const { data: summary, error } = usePoll<AnalyticsSummary>(
    `/api/analytics/channel/${cid}/realtime`, 8000)
  const { data: series } = usePoll<TimeseriesPoint[]>(
    `/api/analytics/channel/${cid}/timeseries`, 8000)
  const { data: board } = usePoll<LeaderboardRow[]>(
    `/api/analytics/leaderboard/${cid}`, 8000)

  const syncNow = async () => { await api.post(`/api/analytics/sync/${cid}`) }
  const learnNow = async () => { await api.post(`/api/analytics/learn/${cid}`) }

  const chart = (series ?? []).map((p) => ({
    ...p,
    time: new Date(p.ts).toLocaleDateString(undefined, { month: 'short', day: 'numeric' }),
  }))

  const connected = summary?.connected ?? false
  const metricsSource = summary?.metrics_source ?? 'none'
  const metricsLabel = metricsSource === 'youtube'
    ? 'LIVE YOUTUBE DATA'
    : metricsSource === 'simulated'
      ? 'SIMULATED TEST DATA'
      : metricsSource === 'mixed'
        ? 'MIXED: LIVE + SIMULATED'
        : 'NO ANALYTICS DATA'
  const metricsTone = metricsSource === 'youtube'
    ? 'border-emerald-500/30 bg-emerald-500/10 text-emerald-300'
    : metricsSource === 'none'
      ? 'border-zinc-700 bg-zinc-800/60 text-zinc-400'
      : 'border-amber-500/30 bg-amber-500/10 text-amber-300'

  return (
    <div>
      <PageHeader title="Analytics">
        <select className="input !w-56" value={cid} onChange={(e) => setChannelId(Number(e.target.value))}>
          {(channels ?? []).map((c) => (
            <option key={c.id} value={c.id}>{c.name}</option>
          ))}
        </select>
        <button className="btn-ghost" onClick={syncNow}>↻ sync now</button>
        <button className="btn-primary" onClick={learnNow}>🧠 run learning</button>
      </PageHeader>

      {summary && (
        <div className={`mb-3 rounded-lg border px-3 py-2 text-xs ${metricsTone}`}>
          <span className="font-semibold tracking-wide">Tracking source: {metricsLabel}</span>
          {metricsSource !== 'youtube' && (
            <span className="ml-2 opacity-80">
              No unavailable YouTube metric is presented as real.
            </span>
          )}
        </div>
      )}

      {/* Live YouTube channel banner */}
      {summary && (
        <div className={`card mb-6 ${connected ? 'border-emerald-500/30' : 'border-amber-500/30'}`}>
          <div className="flex flex-wrap items-center gap-4">
            {summary.yt_thumbnail ? (
              <img src={summary.yt_thumbnail} alt="" className="h-16 w-16 rounded-full"
                onError={(e) => { (e.target as HTMLImageElement).style.display = 'none' }} />
            ) : (
              <div className="flex h-16 w-16 items-center justify-center rounded-full bg-gradient-to-br from-phoenix-500 to-amber-500 text-2xl">
                📺
              </div>
            )}
            <div className="flex-1">
              <div className="flex items-center gap-2">
                <div className="text-lg font-bold text-white">
                  {summary.channel_name || 'Not connected'}
                </div>
                <span className={`rounded-full px-2 py-0.5 text-[10px] font-semibold ${
                  connected ? 'bg-emerald-500/20 text-emerald-300' : 'bg-amber-500/20 text-amber-300'
                }`}>
                  {connected ? '● LIVE' : '○ disconnected'}
                </span>
              </div>
              {summary.yt_channel_id && (
                <div className="mt-0.5 text-[11px] text-phoenix-400">
                  youtube.com/channel/{summary.yt_channel_id}
                </div>
              )}
              {summary.yt_country && (
                <div className="mt-0.5 text-[11px] text-zinc-500">country: {summary.yt_country}</div>
              )}
            </div>
            {connected && (
              <div className="grid grid-cols-3 gap-4 text-center">
                <div>
                  <div className="text-[10px] uppercase text-zinc-500">Subscribers</div>
                  <div className="font-mono text-lg font-bold text-phoenix-300">
                    {summary.yt_subscriber_count != null ? fmt(summary.yt_subscriber_count) : '—'}
                  </div>
                </div>
                <div>
                  <div className="text-[10px] uppercase text-zinc-500">Videos</div>
                  <div className="font-mono text-lg font-bold text-phoenix-300">
                    {summary.yt_video_count != null ? fmt(summary.yt_video_count) : '—'}
                  </div>
                </div>
                <div>
                  <div className="text-[10px] uppercase text-zinc-500">Total views</div>
                  <div className="font-mono text-lg font-bold text-phoenix-300">
                    {summary.yt_total_views != null ? fmt(summary.yt_total_views) : '—'}
                  </div>
                </div>
              </div>
            )}
          </div>
          {!connected && (
            <div className="mt-3 rounded-lg bg-amber-500/10 px-3 py-2 text-xs text-amber-300">
              ⚠ YouTube is not connected. Go to the Channels page and click
              "Connect YouTube" to see live subscriber / view counts here.
              {error && <div className="mt-1 text-rose-300">error: {error}</div>}
            </div>
          )}
        </div>
      )}

      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        <StatCard label="Views" value={fmt(summary?.views ?? 0)} icon="👁" />
        <StatCard label="Watch minutes" value={fmt(summary?.watch_minutes ?? 0)} icon="◷" />
        <StatCard label="Avg retention" value={`${summary?.avg_retention ?? 0}%`} icon="▮" />
        <StatCard label="Subscribers gained" value={fmt(summary?.subs_gained ?? 0)}
          icon="＋" sub={`avg CTR ${summary?.avg_ctr ?? 0}%`} />
      </div>

      <div className="card mt-6">
        <div className="mb-4 text-xs font-semibold uppercase tracking-wider text-zinc-500">
          Performance over time
        </div>
        <div className="h-72">
          <ResponsiveContainer width="100%" height="100%">
            <AreaChart data={chart}>
              <defs>
                <linearGradient id="gViews" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor="#ff5e3a" stopOpacity={0.5} />
                  <stop offset="100%" stopColor="#ff5e3a" stopOpacity={0} />
                </linearGradient>
                <linearGradient id="gSubs" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor="#fbbf24" stopOpacity={0.5} />
                  <stop offset="100%" stopColor="#fbbf24" stopOpacity={0} />
                </linearGradient>
              </defs>
              <CartesianGrid stroke="#232329" strokeDasharray="3 3" />
              <XAxis dataKey="time" stroke="#52525b" fontSize={11} />
              <YAxis stroke="#52525b" fontSize={11} />
              <Tooltip
                contentStyle={{ background: '#141418', border: '1px solid #2e2e36', borderRadius: 12 }}
                labelStyle={{ color: '#a1a1aa' }}
              />
              <Legend />
              <Area type="monotone" dataKey="views" stroke="#ff5e3a" fill="url(#gViews)" strokeWidth={2} />
              <Area type="monotone" dataKey="subs_gained" stroke="#fbbf24" fill="url(#gSubs)" strokeWidth={2} />
            </AreaChart>
          </ResponsiveContainer>
        </div>
        {chart.length === 0 && (
          <div className="py-4 text-center text-xs text-zinc-600">
            {connected
              ? 'no analytics snapshots yet — hit "sync now" to pull live YouTube data'
              : 'connect YouTube and publish a video, then hit "sync now"'}
          </div>
        )}
      </div>

      <div className="card mt-6">
        <div className="mb-4 text-xs font-semibold uppercase tracking-wider text-zinc-500">
          Video leaderboard
        </div>
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-xs uppercase tracking-wider text-zinc-500">
              <th className="pb-2">Video</th>
              <th className="pb-2 text-right">Views</th>
              <th className="pb-2 text-right">Retention</th>
              <th className="pb-2 text-right">CTR</th>
              <th className="pb-2 text-right">Subs</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-ink-700">
            {(board ?? []).map((r) => (
              <tr key={r.video_id}>
                <td className="max-w-md truncate py-2.5 pr-4 text-zinc-200">{r.title}</td>
                <td className="py-2.5 text-right font-mono text-phoenix-300">{fmt(r.views)}</td>
                <td className="py-2.5 text-right font-mono">{r.retention_pct}%</td>
                <td className="py-2.5 text-right font-mono">{r.ctr_pct}%</td>
                <td className="py-2.5 text-right font-mono text-emerald-400">+{r.subs_gained}</td>
              </tr>
            ))}
          </tbody>
        </table>
        {(board ?? []).length === 0 && (
          <div className="py-6 text-center text-xs text-zinc-600">
            {connected ? 'no published videos yet' : 'connect YouTube to start tracking videos'}
          </div>
        )}
      </div>
    </div>
  )
}
