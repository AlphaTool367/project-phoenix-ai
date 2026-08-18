import type { DashboardSummary } from '../lib/types'
import ProgressBar from './ProgressBar'

function labelForKey(key: string): string {
  return key === 'openrouter' ? 'OpenRouter' : key === 'gemini' ? 'Gemini' : key === 'grok' ? 'Grok / xAI' : key.charAt(0).toUpperCase() + key.slice(1)
}

function isConfigured(value: string): boolean {
  return Boolean(value && value.trim())
}

function serviceLabel(value: string): string {
  if (value === 'configured') return 'configured'
  if (value.startsWith('live')) return 'live'
  if (value.startsWith('dry-run')) return 'dry-run'
  if (value.startsWith('mock')) return 'mock/fallback'
  if (value.startsWith('not configured')) return 'not configured'
  if (value.startsWith('off')) return 'off'
  return 'fallback'
}

function serviceClass(value: string): string {
  if (value === 'configured' || value.startsWith('live')) return 'text-emerald-400'
  if (value.startsWith('not configured') || value.startsWith('off')) return 'text-zinc-600'
  return 'text-amber-400'
}

export default function HealthPanel({ summary }: { summary: DashboardSummary }) {
  const sys = summary.system
  const providerEntries = (['openrouter', 'gemini', 'grok'] as const).map((key) => [
    key,
    summary.capabilities.keys?.[key] ?? '',
  ] as const)

  return (
    <div className="card">
      <div className="mb-4 flex items-center justify-between gap-2">
        <div className="text-xs font-semibold uppercase tracking-wider text-zinc-500">
          System & API Health
        </div>
        <span className="rounded-full border border-white/10 bg-white/[0.04] px-2 py-1 text-[10px] text-zinc-500">
          checked {new Date(summary.capabilities.checked_at).toLocaleTimeString()}
        </span>
      </div>
      <div className="space-y-4">
        <ProgressBar pct={sys.cpu_pct} label={`CPU ${sys.cpu_pct}%`} />
        <ProgressBar
          pct={sys.ram_pct}
          label={`RAM ${sys.ram_used_gb}/${sys.ram_total_gb} GB`}
        />
        <ProgressBar
          pct={Math.round((sys.disk_used_gb / Math.max(sys.disk_total_gb, 1)) * 100)}
          label={`Disk ${sys.disk_used_gb}/${sys.disk_total_gb} GB`}
        />
      </div>

      <div className="mt-5 border-t border-white/8 pt-4">
        <div className="mb-2 text-[10px] font-semibold uppercase tracking-[0.18em] text-fuchsia-200/55">
          API provider status
        </div>
        <div className="space-y-2 text-xs">
          {providerEntries.map(([key, masked]) => {
            const configured = isConfigured(masked)
            const service = summary.capabilities.services[key] ?? ''
            const active = configured && service === 'configured'
            return (
              <div key={key} className="flex items-center justify-between gap-3 rounded-lg border border-white/8 bg-ink-800 px-3 py-2">
                <div className="min-w-0">
                  <div className="font-semibold text-zinc-300">{labelForKey(key)}</div>
                  <div className="truncate font-mono text-[10px] text-zinc-600">{configured ? masked : 'no key configured'}</div>
                </div>
                <span className={active ? 'shrink-0 text-emerald-400' : configured ? 'shrink-0 text-amber-400' : 'shrink-0 text-zinc-600'}>
                  {active ? 'configured · ready to try' : configured ? 'configured · forced mock' : 'not configured'}
                </span>
              </div>
            )
          })}
        </div>
        <div className="mt-2 text-[10px] leading-relaxed text-zinc-600">
          Keys are masked. “Configured · ready to try” means the key is present and the provider is enabled; provider quotas, connectivity and request success remain provider-controlled.
        </div>
      </div>

      <div className="mt-5 grid grid-cols-2 gap-2 text-xs">
        {Object.entries(summary.capabilities.services).map(([k, v]) => (
          <div key={k} className="flex items-center justify-between rounded-lg bg-ink-800 px-3 py-2">
            <span className="font-semibold text-zinc-400">{k}</span>
            <span className={serviceClass(v)}>{serviceLabel(v)}</span>
          </div>
        ))}
      </div>
      <div className="mt-3 text-[11px] text-zinc-600">
        ffmpeg: {summary.capabilities.ffmpeg} · uptime {sys.uptime_min} min
      </div>
    </div>
  )
}
