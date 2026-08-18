import { ReactNode } from 'react'

export default function StatCard({
  label,
  value,
  sub,
  icon,
}: {
  label: string
  value: ReactNode
  sub?: string
  icon?: ReactNode
}) {
  return (
    <div className="card">
      <div className="flex items-start justify-between">
        <div>
          <div className="text-xs font-semibold uppercase tracking-wider text-zinc-500">{label}</div>
          <div className="mt-2 text-3xl font-bold text-white">{value}</div>
          {sub && <div className="mt-1 text-xs text-zinc-500">{sub}</div>}
        </div>
        {icon && <div className="text-2xl opacity-70">{icon}</div>}
      </div>
    </div>
  )
}
