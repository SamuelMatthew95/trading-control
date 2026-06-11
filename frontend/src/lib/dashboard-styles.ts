// Shared dashboard surface classes — dual-theme.
// Light is the base utility; the redesign's dark "operator console" look is the
// `dark:` variant. Keep both in sync so every page renders coherently in either
// theme (see ThemeToggle / next-themes, defaultTheme="dark").

export const cardClass =
  'rounded-xl border border-slate-200 bg-white p-3 shadow-sm shadow-slate-900/5 transition-colors duration-150 hover:border-slate-300 dark:border-slate-800/80 dark:bg-slate-950/80 dark:shadow-black/20 dark:hover:border-slate-700 sm:p-4'

export const sectionTitleClass =
  'text-[11px] font-semibold uppercase tracking-[0.18em] font-sans text-slate-500 dark:text-slate-400'

export const mutedClass = 'text-xs font-sans text-slate-500 dark:text-slate-400'

export const valueClass =
  'text-2xl font-semibold font-mono tabular-nums text-slate-900 dark:text-slate-100'

export const consolePanelClass =
  'rounded-xl border border-slate-200 bg-white shadow-sm shadow-slate-900/5 dark:border-slate-800/80 dark:bg-slate-950/80 dark:shadow-black/20'

export const consoleHeaderClass =
  'border-b border-slate-200 px-3 py-2 dark:border-slate-800/80'

/** Inline panel error label — `err: <message>` in a panel header. */
export const errorTextClass = 'font-mono text-xs text-danger'

/** Monospace data value inside body copy (counts, ids, provider names). */
export const monoValueClass = 'font-mono text-slate-700 dark:text-slate-300'

/** Chip shape — compose colour with a Tone map (e.g. TONE_BADGE_OUTLINED). */
export const chipClass =
  'inline-flex items-center gap-1 rounded-md border px-2 py-0.5 text-xs font-medium'
