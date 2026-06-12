// Shared dashboard surface classes — expressed entirely in design tokens
// (tailwind.config.js + src/styles/globals.css), so light/dark parity and the
// palette live in one place. Compose these; never re-declare a surface recipe
// at a call site.

export const cardClass =
  'rounded-xl border bg-card p-3 shadow-card transition-colors duration-150 hover:border-strong dark:bg-card/80 sm:p-4'

export const sectionTitleClass =
  'text-2xs font-semibold uppercase tracking-caps font-sans text-muted-foreground'

export const mutedClass = 'text-xs font-sans text-muted-foreground'

export const valueClass = 'text-2xl font-semibold font-mono tabular-nums text-foreground'

export const consolePanelClass = 'rounded-xl border bg-card shadow-card dark:bg-card/80'

export const consoleHeaderClass = 'border-b px-3 py-2'

/** Inline panel error label — `err: <message>` in a panel header. */
export const errorTextClass = 'font-mono text-xs text-danger'

/** Monospace data value inside body copy (counts, ids, provider names). */
export const monoValueClass = 'font-mono text-foreground/80'

/** Chip shape — compose colour with a Tone map (e.g. TONE_BADGE_OUTLINED). */
export const chipClass =
  'inline-flex items-center gap-1 rounded-md border px-2 py-0.5 text-xs font-medium'
