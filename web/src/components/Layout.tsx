import type { ReactNode } from "react";
import { NavLink } from "react-router-dom";
import { Briefcase, FileText, LayoutDashboard, Moon, Plane, Sun } from "lucide-react";
import { useTheme } from "@/lib/theme";
import { cn } from "@/lib/utils";

const NAV = [
  { to: "/", label: "Deck", icon: LayoutDashboard, end: true },
  { to: "/jobs", label: "Jobs", icon: Briefcase, end: false },
  { to: "/cv", label: "CV Studio", icon: FileText, end: false },
];

export function Layout({ live, children }: { live: boolean; children: ReactNode }) {
  const { theme, toggle } = useTheme();

  return (
    <div className="flex min-h-screen">
      {/* Sidebar */}
      <aside className="sticky top-0 flex h-screen w-56 shrink-0 flex-col border-r bg-surface/60 px-3 py-5">
        <div className="flex items-center gap-2 px-2">
          <span className="grid h-8 w-8 place-items-center rounded-lg bg-accent text-accent-ink">
            <Plane size={17} className="-rotate-45" />
          </span>
          <span className="font-display text-lg font-semibold tracking-tight">JobPilot</span>
        </div>

        <nav className="mt-8 flex flex-col gap-1">
          {NAV.map(({ to, label, icon: Icon, end }) => (
            <NavLink
              key={to}
              to={to}
              end={end}
              className={({ isActive }) =>
                cn(
                  "flex items-center gap-2.5 rounded-lg px-3 py-2 text-sm font-medium transition-colors",
                  isActive
                    ? "bg-accent/12 text-ink [box-shadow:inset_2px_0_0_var(--accent)]"
                    : "text-ink-muted hover:bg-surface-2 hover:text-ink",
                )
              }
            >
              <Icon size={17} />
              {label}
            </NavLink>
          ))}
        </nav>

        <div className="mt-auto px-2 text-[11px] leading-relaxed text-ink-muted">
          Local control plane · single user
        </div>
      </aside>

      {/* Main column */}
      <div className="flex min-w-0 flex-1 flex-col">
        <header className="sticky top-0 z-10 flex h-14 items-center justify-between border-b bg-bg/80 px-6 backdrop-blur">
          <LiveIndicator live={live} />
          <button
            onClick={toggle}
            aria-label={theme === "dark" ? "Switch to light" : "Switch to dark"}
            className="grid h-8 w-8 place-items-center rounded-lg text-ink-muted hover:bg-surface-2 hover:text-ink"
          >
            {theme === "dark" ? <Sun size={16} /> : <Moon size={16} />}
          </button>
        </header>

        <main className="mx-auto w-full max-w-6xl flex-1 px-6 py-6">{children}</main>
      </div>
    </div>
  );
}

function LiveIndicator({ live }: { live: boolean }) {
  return (
    <div className="flex items-center gap-2 text-xs font-medium">
      <span className="relative flex h-2 w-2">
        {live && (
          <span className="absolute inline-flex h-full w-full animate-beacon rounded-full bg-live" />
        )}
        <span
          className={cn("relative inline-flex h-2 w-2 rounded-full", live ? "bg-live" : "bg-ink-muted/50")}
        />
      </span>
      <span className={cn("font-mono uppercase tracking-widest", live ? "text-live" : "text-ink-muted")}>
        {live ? "Live" : "Offline"}
      </span>
    </div>
  );
}
