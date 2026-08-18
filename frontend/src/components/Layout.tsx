import { ReactNode } from 'react'
import { NavLink, Outlet } from 'react-router-dom'

const NAV = [
  { to: '/', label: 'Dashboard', icon: '◈' },
  { to: '/videos', label: 'Videos', icon: '▶' },
  { to: '/cartoons', label: 'Cartoons', icon: '🎬' },
  { to: '/ai-story', label: 'AI Story', icon: '🤖' },
  { to: '/remix', label: 'Remix', icon: '🔄' },
  { to: '/channels', label: 'Channels', icon: '☰' },
  { to: '/analytics', label: 'Analytics', icon: '↗' },
  { to: '/monitor', label: 'YT Monitor', icon: '📡' },
  { to: '/scheduler', label: 'Scheduler', icon: '◷' },
  { to: '/logs', label: 'AI Activity', icon: '≡' },
  { to: '/safety', label: 'Safety Center', icon: '🛡' },
  { to: '/settings', label: 'Settings', icon: '⚙' },
]

export function PageHeader({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className="mb-6 flex flex-wrap items-center justify-between gap-3">
      <div>
        <div className="mb-1 text-[10px] font-semibold uppercase tracking-[0.28em] text-fuchsia-200/45">
          Phoenix control room
        </div>
        <h1 className="text-2xl font-bold tracking-tight text-white drop-shadow-[0_0_18px_rgba(239,159,232,0.12)]">{title}</h1>
      </div>
      <div className="flex items-center gap-2">{children}</div>
    </div>
  )
}

export default function Layout() {
  return (
    <div className="min-h-screen bg-transparent">
      <div className="pointer-events-none fixed -left-24 top-24 z-0 h-72 w-72 rounded-full bg-fuchsia-400/10 blur-3xl" />
      <div className="pointer-events-none fixed bottom-0 right-0 z-0 h-96 w-96 rounded-full bg-violet-500/10 blur-3xl" />
      <aside className="fixed inset-y-0 left-0 z-20 flex w-60 flex-col border-r border-white/10 bg-black/35 shadow-[18px_0_60px_rgba(0,0,0,0.22)] backdrop-blur-2xl">
        <div className="mx-3 mt-3 rounded-2xl border border-white/10 bg-white/[0.045] px-4 py-5 shadow-[inset_0_1px_0_rgba(255,255,255,0.08)]">
          <div className="flex items-center gap-3">
            <div className="relative flex h-10 w-10 items-center justify-center rounded-2xl border border-fuchsia-100/30 bg-gradient-to-br from-fuchsia-300 via-pink-300 to-violet-400 text-xl font-black text-[#241228] shadow-[0_0_30px_rgba(239,159,232,0.35)]">
              <span className="absolute inset-1 rounded-xl border border-white/35" />
              <span className="relative">✦</span>
            </div>
            <div>
              <div className="text-sm font-bold leading-tight text-white">Project Phoenix</div>
              <div className="mt-0.5 text-[10px] font-semibold uppercase tracking-[0.16em] text-fuchsia-200/70">AI YouTube Studio</div>
            </div>
          </div>
          <div className="mt-4 flex items-center justify-between rounded-full border border-emerald-200/15 bg-emerald-300/[0.06] px-3 py-1.5 text-[10px] text-emerald-200/80">
            <span className="flex items-center gap-1.5"><span className="h-1.5 w-1.5 rounded-full bg-emerald-300 shadow-[0_0_8px_rgba(110,231,183,0.9)]" /> Studio online</span>
            <span className="text-white/35">v1.0</span>
          </div>
        </div>
        <nav className="mt-5 flex min-h-0 flex-1 flex-col space-y-1 overflow-y-auto px-3 pb-2">
          {NAV.map((n) => (
            <NavLink
              key={n.to}
              to={n.to}
              end={n.to === '/'}
              className={({ isActive }) =>
                `group relative flex w-full shrink-0 items-center gap-3 rounded-xl border px-3 py-2.5 text-sm font-medium transition-all duration-200 ${
                  isActive
                    ? 'border-fuchsia-200/25 bg-gradient-to-r from-fuchsia-200/20 via-fuchsia-200/[0.07] to-transparent text-white shadow-[0_0_26px_rgba(239,159,232,0.1)]'
                    : 'border-transparent text-zinc-400 hover:border-white/10 hover:bg-white/[0.055] hover:text-fuchsia-100'
                }`
              }
            >
              {({ isActive }) => (
                <>
                  <span className={`absolute left-0 h-5 w-0.5 rounded-full bg-fuchsia-200 shadow-[0_0_10px_rgba(239,159,232,0.9)] transition-opacity ${isActive ? 'opacity-100' : 'opacity-0'}`} />
                  <span className="w-5 text-center text-base opacity-80 transition-transform duration-200 group-hover:scale-110">{n.icon}</span>
                  {n.label}
                </>
              )}
            </NavLink>
          ))}
        </nav>
        <div className="mx-3 mb-3 rounded-xl border border-white/8 bg-white/[0.035] px-3 py-3 text-[10px] leading-relaxed text-fuchsia-100/40">
          <div className="mb-1 uppercase tracking-[0.2em] text-fuchsia-100/55">Studio mode</div>
          Glass command surface · self-learning workflows
        </div>
      </aside>
      <main className="relative z-10 ml-60 min-h-screen p-8">
        <Outlet />
      </main>
    </div>
  )
}
