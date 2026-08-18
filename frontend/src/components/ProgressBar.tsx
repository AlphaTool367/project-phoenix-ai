export default function ProgressBar({
  pct,
  label,
}: {
  pct: number
  label?: string
}) {
  return (
    <div>
      {label && (
        <div className="mb-1 flex justify-between text-xs text-zinc-400">
          <span>{label}</span>
          <span className="font-mono">{pct}%</span>
        </div>
      )}
      <div className="h-2 overflow-hidden rounded-full bg-ink-700">
        <div
          className="h-full rounded-full bg-gradient-to-r from-phoenix-500 to-amber-400 transition-all duration-500"
          style={{ width: `${Math.min(pct, 100)}%` }}
        />
      </div>
    </div>
  )
}
