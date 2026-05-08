/**
 * Design system tokens — operator-grade terminal aesthetic.
 *
 * Dense layout. Monospace numerics. Small radii. Color reserved for state.
 * No gradients. No marketing pill buttons. No purple SaaS palette.
 */

export const UI_RADIUS = {
  button: 'rounded-[4px]',
  card: 'rounded-[6px]',
  chip: 'rounded-[4px]',
  panel: 'rounded-[8px]',
} as const

export const UI_TEXT = {
  /** Section / column headers — uppercase mono. */
  label: 'font-mono text-[11px] uppercase tracking-[0.04em] text-slate-500 dark:text-slate-400',
  /** Numeric values — monospace tabular for column alignment. */
  numeric: 'font-mono tabular-nums',
  /** Body text. */
  body: 'text-sm text-slate-700 dark:text-slate-300',
  /** Muted inline text. */
  muted: 'text-xs text-slate-500 dark:text-slate-400',
  /** Headline numeric value (large metric display). */
  metric: 'text-2xl font-semibold font-mono tabular-nums text-slate-950 dark:text-slate-100',
  /** Small numeric value (dense table cells). */
  cell: 'text-sm font-mono tabular-nums text-slate-900 dark:text-slate-100',
} as const

/** Surface / card background tokens. */
export const UI_SURFACE = {
  card: 'border border-slate-200 bg-white dark:border-slate-800 dark:bg-slate-900',
  cardHover: 'hover:border-slate-300 dark:hover:border-slate-600',
  sunken: 'border border-slate-200 bg-slate-50 dark:border-slate-800 dark:bg-slate-950',
} as const

/** Standard padding tokens. */
export const UI_PAD = {
  card: 'p-4 sm:p-5',
  tile: 'p-3',
  cell: 'px-2 py-2',
  cellDense: 'px-2 py-1.5',
} as const

/** Standard button height — never bigger than 28px in this UI. */
export const BUTTON_HEIGHT = 'h-7'
