import { useEffect, useRef, useState } from 'react'
import type { LogEntry } from './types'

const BASE = ''

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const r = await fetch(`${BASE}${path}`, {
    headers: { 'Content-Type': 'application/json' },
    ...init,
  })
  if (!r.ok) {
    const detail = await r.text().catch(() => '')
    throw new Error(`${r.status} ${r.statusText}: ${detail.slice(0, 200)}`)
  }
  return r.json() as Promise<T>
}

export const api = {
  get: <T>(path: string) => req<T>(path),
  post: <T>(path: string, body?: unknown) =>
    req<T>(path, { method: 'POST', body: body ? JSON.stringify(body) : undefined }),
  patch: <T>(path: string, body: unknown) =>
    req<T>(path, { method: 'PATCH', body: JSON.stringify(body) }),
  delete: <T>(path: string) =>
    req<T>(path, { method: 'DELETE' }),
}

/** Poll an endpoint on an interval. */
export function usePoll<T>(path: string, intervalMs = 5000) {
  const [data, setData] = useState<T | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let alive = true
    const tick = async () => {
      try {
        const d = await api.get<T>(path)
        if (alive) {
          setData(d)
          setError(null)
        }
      } catch (e) {
        if (alive) setError(e instanceof Error ? e.message : String(e))
      }
    }
    tick()
    const id = setInterval(tick, intervalMs)
    return () => {
      alive = false
      clearInterval(id)
    }
  }, [path, intervalMs])

  return { data, error }
}

/** Live activity stream over WebSocket (falls back silently if unavailable). */
export function useLogStream(maxEntries = 200) {
  const [entries, setEntries] = useState<LogEntry[]>([])
  const [connected, setConnected] = useState(false)
  const bufRef = useRef<LogEntry[]>([])

  useEffect(() => {
    const proto = location.protocol === 'https:' ? 'wss' : 'ws'
    const ws = new WebSocket(`${proto}://${location.host}/ws/logs`)
    ws.onopen = () => setConnected(true)
    ws.onclose = () => setConnected(false)
    ws.onmessage = (ev) => {
      try {
        const entry = JSON.parse(ev.data) as LogEntry
        bufRef.current = [...bufRef.current.slice(-(maxEntries - 1)), entry]
        setEntries(bufRef.current)
      } catch {
        /* ignore malformed frames */
      }
    }
    return () => ws.close()
  }, [maxEntries])

  return { entries, connected }
}

export function timeAgo(iso: string | null): string {
  if (!iso) return '—'
  const s = (Date.now() - new Date(iso).getTime()) / 1000
  if (s < 60) return `${Math.floor(s)}s ago`
  if (s < 3600) return `${Math.floor(s / 60)}m ago`
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`
  return `${Math.floor(s / 86400)}d ago`
}

export function fmt(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`
  return String(Math.round(n))
}
