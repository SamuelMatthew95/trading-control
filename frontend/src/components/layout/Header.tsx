import { ThemeToggle } from "@/components/theme/ThemeToggle";

interface HeaderProps {
  title: string;
  subtitle?: string;
}

export function Header({ title, subtitle }: HeaderProps) {
  return (
    <header className="h-12 border-b border-slate-200 bg-slate-50 px-4 dark:border-slate-800 dark:bg-slate-950">
      <div className="mx-auto flex h-full max-w-7xl items-center justify-between gap-4">
        <div>
          <h1 className="text-sm font-sans font-bold uppercase tracking-widest text-slate-900 dark:text-slate-100">
            {title}
          </h1>
          {subtitle && (
            <p className="text-xs font-sans text-slate-500 dark:text-slate-400">
              {subtitle}
            </p>
          )}
        </div>

        <div className="flex items-center gap-3">
          <div className="flex items-center gap-2 text-xs font-sans text-slate-500 dark:text-slate-400">
            <span className="h-2 w-2 rounded-full bg-emerald-500 animate-pulse" />
            <span>LIVE</span>
            <span className="font-mono tabular-nums">
              {new Date().toLocaleTimeString([], {
                hour: "2-digit",
                minute: "2-digit",
              })}
            </span>
          </div>

          <ThemeToggle />
        </div>
      </div>
    </header>
  );
}
