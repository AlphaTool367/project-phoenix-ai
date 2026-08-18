const COLORS: Record<string, string> = {
  published: 'bg-emerald-300/10 text-emerald-200 border-emerald-200/25 shadow-[0_0_14px_rgba(110,231,183,0.10)]',
  scheduled: 'bg-sky-300/10 text-sky-200 border-sky-200/25',
  rendering: 'bg-amber-300/10 text-amber-100 border-amber-200/25 shadow-[0_0_14px_rgba(252,211,77,0.08)]',
  uploading: 'bg-amber-300/10 text-amber-100 border-amber-200/25',
  awaiting_review: 'bg-fuchsia-300/12 text-fuchsia-100 border-fuchsia-200/30 shadow-[0_0_16px_rgba(239,159,232,0.12)]',
  rendered: 'bg-violet-300/10 text-violet-100 border-violet-200/25',
  failed: 'bg-rose-300/10 text-rose-100 border-rose-200/25',
  queued: 'bg-white/5 text-white/55 border-white/10',
  running: 'bg-amber-300/10 text-amber-100 border-amber-200/25',
  done: 'bg-emerald-300/10 text-emerald-200 border-emerald-200/25',
  dead: 'bg-rose-300/10 text-rose-100 border-rose-200/25',
  planned: 'bg-white/5 text-white/55 border-white/10',
  cancelled: 'bg-white/5 text-white/40 border-white/10',
}

export default function StatusBadge({ status }: { status: string }) {
  const cls = COLORS[status] ?? 'bg-white/5 text-white/60 border-white/10'
  return (
    <span className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-0.5 text-[11px] font-semibold backdrop-blur-md ${cls}`}>
      <span className="h-1.5 w-1.5 rounded-full bg-current shadow-[0_0_8px_currentColor]" />
      {status.replace('_', ' ')}
    </span>
  )
}
