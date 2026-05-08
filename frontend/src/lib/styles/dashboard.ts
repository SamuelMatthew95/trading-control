/**
 * Centralized class-bundle constants for the dashboard surface.
 *
 * Every Tailwind chain that previously appeared inline in 2+ components
 * (and many of the one-off chains that are non-trivial enough to deserve
 * a name) lives here under a named export. Components consume these
 * constants via `cn(STYLE_BUNDLE, ...)` so that:
 *
 *   1. Visual tweaks happen in ONE place.
 *   2. The names communicate intent ("inner tile", "trace button") instead
 *      of asking the reader to decode color tokens.
 *   3. Grep finds every consumer of a given pattern.
 *
 * Color comes from Tone (lib/state/tone) via TONE_CLASSES — the constants
 * here are intentionally tone-free and compose with TONE_CLASSES at use site.
 */

// ── Layout primitives ─────────────────────────────────────────────────────

export const STACK = 'space-y-4'
export const STACK_TIGHT = 'space-y-2'
export const STACK_LOOSE = 'space-y-3'

export const ROW_BETWEEN = 'flex items-center justify-between'
export const ROW_START = 'flex items-center gap-2'
export const ROW_END = 'flex shrink-0 items-center gap-2'
export const ROW_WRAP = 'flex flex-wrap items-center gap-2'

// ── Inner tile (the small bordered cell that lives inside a TerminalCard) ──
// Used in PnL summary tiles, metric grids, system panels, learning summary,
// price tiles, persisted-history panels, etc.
export const INNER_TILE =
  'rounded-[6px] border border-slate-300 p-3 dark:border-slate-800'

export const PRICE_TILE = INNER_TILE

// Inline event row (looks like a tile, but laid out as a single row).
export const EVENT_ROW =
  'flex items-center justify-between rounded-[6px] border border-slate-300 px-3 py-2 dark:border-slate-800'

// ── Bordered chip bases (compose with TONE_CLASSES[tone].chip / .soft) ────

export const CHIP_BASE = 'rounded-[4px] px-2 py-0.5 text-xs font-semibold uppercase'
export const CHIP_BASE_BOLD = 'rounded-[4px] px-2 py-0.5 text-xs font-bold uppercase'
export const SCORE_CHIP = 'rounded-[4px] px-2 py-0.5 text-xs font-semibold'

/** Compact mono confidence-style chip used inline in lists. */
export const MONO_CHIP =
  'rounded-[4px] bg-slate-100 px-2 py-0.5 text-xs font-mono text-slate-500 dark:bg-slate-800'

/** Pending-count badge. */
export const PENDING_COUNT_CHIP =
  'rounded-[4px] bg-slate-200 px-2 py-0.5 text-xs font-bold text-slate-900 dark:bg-slate-700 dark:text-slate-100'

// ── Buttons ───────────────────────────────────────────────────────────────

export const TRACE_BUTTON =
  'rounded-[4px] px-1.5 py-0.5 text-[10px] font-mono text-slate-500 transition-colors hover:bg-slate-100 hover:text-slate-700 dark:hover:bg-slate-800'

export const LIST_HOVER_BUTTON =
  'flex w-full items-center justify-between rounded-[4px] px-1 py-1 text-left text-xs font-mono hover:bg-slate-100 dark:hover:bg-slate-800'

export const VOTE_BUTTON_BASE =
  'flex items-center gap-1.5 rounded-[4px] px-3 py-1 text-xs font-semibold transition-colors'

// ── Row dividers ──────────────────────────────────────────────────────────

export const ROW_DIVIDER = 'border-t border-slate-300 dark:border-slate-800'
export const ROW_DIVIDER_SKIP_FIRST =
  'border-t border-slate-300 first:border-t-0 dark:border-slate-800'

// ── Banner card surface (compose with TONE_CLASSES[tone].card / .text) ────

export const BANNER_BASE = 'rounded-[6px] p-3 text-sm'

// ── Sub-panel grids (responsive column layouts used in System section) ────

export const SUB_PANEL_GRID = 'grid grid-cols-1 gap-2 sm:grid-cols-3'
export const SUB_PANEL_GRID_2 = 'grid grid-cols-1 gap-3 lg:grid-cols-2'
export const SUB_PANEL_GRID_4 = 'grid grid-cols-1 gap-2 sm:grid-cols-4'
export const SUB_PANEL_GRID_5 = 'grid grid-cols-1 gap-2 sm:grid-cols-2 lg:grid-cols-5'
export const SUB_PANEL_GRID_6 = 'grid grid-cols-2 gap-2 sm:grid-cols-6'

/** 4-column metric row used in dashboard headers. */
export const METRIC_ROW_GRID = 'grid grid-cols-1 gap-3 sm:grid-cols-4'
export const METRIC_ROW_GRID_LG = 'grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4 lg:gap-4'
export const METRIC_ROW_GRID_2 = 'grid grid-cols-2 gap-3 sm:grid-cols-4'

/** 1-2-2 column matrix used on overview (equity curve + agent matrix). */
export const SPLIT_GRID = 'grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4 lg:gap-4'

/** Price-tile responsive grid. */
export const PRICE_TILE_GRID = 'grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3'

/** Pipeline streams 2x4 grid. */
export const PIPELINE_STREAM_GRID = 'grid grid-cols-1 gap-2 sm:grid-cols-2 lg:grid-cols-4'

/** Notification facts 2x4 grid. */
export const NOTIFICATION_FACTS_GRID = 'mt-3 grid grid-cols-2 gap-x-3 gap-y-2 sm:grid-cols-4'

// ── Scrollable list constraints ───────────────────────────────────────────

export const SCROLL_LIST_TIGHT = 'max-h-72 space-y-2 overflow-y-auto'
export const SCROLL_LIST_TALL = 'max-h-96 space-y-3 overflow-y-auto'
export const SCROLL_LIST_TABLE = 'max-h-96 overflow-y-auto'
export const SCROLL_LIST_AGENT_LOG = 'relative max-h-80 overflow-y-auto'
export const SCROLL_LIST_TRADE_FEED = 'max-h-96 space-y-1 overflow-y-auto'
export const SCROLL_LIST_INSTANCES = 'max-h-48 overflow-y-auto'

// ── Modal surface ─────────────────────────────────────────────────────────

export const MODAL_OVERLAY =
  'fixed inset-0 z-50 flex items-start justify-center bg-black/60 p-4 pt-16'
export const MODAL_PANEL =
  'max-h-[80vh] w-full max-w-3xl overflow-y-auto rounded-[8px] border border-slate-300 bg-white p-5 shadow-2xl dark:border-slate-700 dark:bg-slate-900'

// ── Typography fragments (reused alongside UI_TEXT.* tokens) ──────────────

/** Strong slate text used in mono key/value pairs. */
export const STRONG_MONO = 'font-mono text-slate-700 dark:text-slate-200'

/** Primary heading text used inside cells / rows. */
export const PRIMARY_TEXT = 'text-slate-900 dark:text-slate-100'

/** Secondary body text used in row sub-content. */
export const SECONDARY_TEXT = 'text-slate-600 dark:text-slate-400'

/** Tertiary muted text. */
export const TERTIARY_TEXT = 'text-slate-500'

/** Mono cell text used for compact key/value rows. */
export const COMPACT_MONO_ROW = 'flex items-center justify-between text-xs font-mono'

/** Trade-feed symbol label. */
export const SYMBOL_LABEL = 'text-sm font-mono font-semibold text-slate-900 dark:text-slate-100'

/** Bold inline title used inside row headers. */
export const ROW_TITLE_BOLD = 'text-sm font-bold text-slate-900 dark:text-slate-100'

/** Compact uptime/timestamp value rendered in 11px mono. */
export const TINY_MONO = 'text-[11px] font-mono text-slate-500'

/** Even smaller mono used for break-all URL values. */
export const URL_MONO = 'mt-1 break-all text-[10px] font-mono text-slate-400'

// ── Skeleton bars used by PriceTileSkeleton ───────────────────────────────

export const SKELETON_BAR_BASE = 'animate-pulse rounded bg-slate-200 dark:bg-slate-700'
export const SKELETON_LABEL = 'mb-1 h-3 w-16 ' + SKELETON_BAR_BASE
export const SKELETON_VALUE = 'mt-1 h-6 w-24 ' + SKELETON_BAR_BASE
export const SKELETON_TINY = 'h-3 w-16 ' + SKELETON_BAR_BASE
export const SKELETON_TINIER = 'h-3 w-12 ' + SKELETON_BAR_BASE

// ── Icon size shortcuts (used in lots of leading icons) ───────────────────

export const ICON_XS = 'h-3 w-3'
export const ICON_SM = 'h-4 w-4'

// ── Specific element fragments that recur ─────────────────────────────────

/** Bottom fade gradient used to indicate scroll affordance. */
export const SCROLL_FADE_BOTTOM =
  'pointer-events-none absolute inset-x-0 bottom-0 h-8 bg-gradient-to-t from-white to-transparent dark:from-slate-900'

/** Notification card icon container (square 9x9 with soft tone bg). */
export const NOTIFICATION_ICON_BOX =
  'mt-0.5 flex h-9 w-9 shrink-0 items-center justify-center rounded-[6px]'

/** Notification card outer surface (border + small radius). */
export const NOTIFICATION_CARD = 'rounded-[6px] border px-3 py-3'

/** Numeric mono fact value inside a NotificationFeed fact row. */
export const NOTIFICATION_FACT_VALUE = 'truncate text-xs font-mono font-semibold tabular-nums'

/** Reconnect banner inside the dashboard header. */
export const RECONNECT_BANNER = 'border-b px-4 py-2 text-xs font-semibold'
