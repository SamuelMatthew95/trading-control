/**
 * Design-system guardrails — source-scan tests in the spirit of the backend's
 * test_field_name_guardrails. They fail CI when a cleaned-up pattern creeps
 * back into production code:
 *
 *   1. Hardcoded semantic colours (emerald/green/rose/red/amber/yellow
 *      utilities) — state must map to a Tone token (text-success, bg-danger/10,
 *      border-warning/30, …) so the palette and light/dark parity live only in
 *      src/styles/globals.css. Categorical palettes are exempt: the grade
 *      module (src/lib/grade-colors.ts) and individual lines carrying an
 *      explicit `categorical-hue:` justification marker.
 *
 *   2. Raw console calls — all logging routes through createLogger
 *      (src/lib/logger.ts) so namespacing and production level policy live in
 *      one place. (ESLint also enforces this; the test keeps it enforced even
 *      if the lint config regresses.)
 *
 *   3. Raw `var(--accent)` colour reads — Tailwind consumes `--accent` as an
 *      HSL triple (`hsl(var(--accent))`), so reading it as a raw colour is
 *      invalid CSS in dark mode. The brand colour is the `brand` token (text-brand).
 *
 *   4. Inline `style={…}` props — presentation lives in the styling system.
 *      The single sanctioned exception is the shared Meter primitive, whose
 *      data-driven fill width cannot be a static class.
 *
 *   5. Arbitrary font-size / letter-spacing utilities (text-[11px],
 *      tracking-[0.16em]) — the type scale lives in tailwind.config.js
 *      (text-2xs/text-3xs, tracking-caps/tracking-caps-wide).
 *
 *   6. Numeric z-index utilities (z-10, z-50) — stacking uses the semantic
 *      scale (z-sticky/z-overlay/z-sidebar/z-header/z-toast/z-modal).
 */
import { describe, it, expect } from 'vitest'
import { readFileSync, readdirSync, statSync } from 'fs'
import { join, relative } from 'path'

const SRC_ROOT = join(__dirname, '..', '..')

/** Files allowed to define categorical hue palettes wholesale. */
const CATEGORICAL_PALETTE_FILES = new Set(['lib/grade-colors.ts'])

/** Per-line escape hatch — must carry a justification after the marker. */
const CATEGORICAL_LINE_MARKER = 'categorical-hue:'

const SEMANTIC_HUE_CLASS =
  /\b(?:text|bg|border|ring|from|via|to|fill|stroke|outline|decoration|divide|shadow|accent|caret)-(?:emerald|green|rose|red|amber|yellow|indigo)-\d{2,3}\b/

/** The one component allowed an inline style: data-driven Meter fill width. */
const INLINE_STYLE_EXEMPT_FILES = new Set(['components/ui/meter.tsx'])

const INLINE_STYLE_PROP = /\bstyle=\{/

/** Arbitrary px font sizes and em trackings — must use the configured scale. */
const ARBITRARY_TYPE_UTILITY = /\b(?:text-\[\d+(?:\.\d+)?px\]|tracking-\[)/

/** Numeric z-index utilities — must use the semantic stacking scale. */
const NUMERIC_Z_UTILITY = /\bz-\d+\b/

function walkSourceFiles(dir: string, out: string[] = []): string[] {
  for (const entry of readdirSync(dir)) {
    const full = join(dir, entry)
    const rel = relative(SRC_ROOT, full)
    if (rel.startsWith('test')) continue
    if (rel.includes('__tests__')) continue
    if (statSync(full).isDirectory()) {
      walkSourceFiles(full, out)
    } else if (/\.(ts|tsx)$/.test(entry)) {
      out.push(full)
    }
  }
  return out
}

const sourceFiles = walkSourceFiles(SRC_ROOT)

describe('design-system guardrails', () => {
  it('scans a sane number of source files (walker is not silently broken)', () => {
    expect(sourceFiles.length).toBeGreaterThan(50)
  })

  it('no hardcoded semantic colour classes outside the categorical palette exemptions', () => {
    const violations: string[] = []
    for (const file of sourceFiles) {
      const rel = relative(SRC_ROOT, file)
      if (CATEGORICAL_PALETTE_FILES.has(rel)) continue
      const lines = readFileSync(file, 'utf8').split('\n')
      lines.forEach((line, i) => {
        if (line.includes(CATEGORICAL_LINE_MARKER)) return
        if (SEMANTIC_HUE_CLASS.test(line)) {
          violations.push(`${rel}:${i + 1}: ${line.trim()}`)
        }
      })
    }
    expect(
      violations,
      `Hardcoded semantic colours found — map the state to a Tone token ` +
        `(src/lib/design/sentiment.ts) or, for a genuinely categorical legend, ` +
        `add a "${CATEGORICAL_LINE_MARKER} <reason>" marker:\n${violations.join('\n')}`,
    ).toEqual([])
  })

  it('no raw console calls outside src/lib/logger.ts', () => {
    const violations: string[] = []
    for (const file of sourceFiles) {
      const rel = relative(SRC_ROOT, file)
      if (rel === 'lib/logger.ts') continue
      const lines = readFileSync(file, 'utf8').split('\n')
      lines.forEach((line, i) => {
        if (/\bconsole\.(log|info|warn|error|debug|trace)\(/.test(line)) {
          violations.push(`${rel}:${i + 1}: ${line.trim()}`)
        }
      })
    }
    expect(
      violations,
      `Raw console calls found — use createLogger from @/lib/logger:\n${violations.join('\n')}`,
    ).toEqual([])
  })

  it('no inline style props outside the Meter primitive', () => {
    const violations: string[] = []
    for (const file of sourceFiles) {
      const rel = relative(SRC_ROOT, file)
      if (INLINE_STYLE_EXEMPT_FILES.has(rel)) continue
      const lines = readFileSync(file, 'utf8').split('\n')
      lines.forEach((line, i) => {
        if (INLINE_STYLE_PROP.test(line)) {
          violations.push(`${rel}:${i + 1}: ${line.trim()}`)
        }
      })
    }
    expect(
      violations,
      `Inline style props found — express presentation in Tailwind tokens, or use the ` +
        `shared <Meter> for data-driven widths:\n${violations.join('\n')}`,
    ).toEqual([])
  })

  it('no arbitrary font-size/tracking utilities (use text-2xs/3xs, tracking-caps)', () => {
    const violations: string[] = []
    for (const file of sourceFiles) {
      const rel = relative(SRC_ROOT, file)
      const lines = readFileSync(file, 'utf8').split('\n')
      lines.forEach((line, i) => {
        if (ARBITRARY_TYPE_UTILITY.test(line)) {
          violations.push(`${rel}:${i + 1}: ${line.trim()}`)
        }
      })
    }
    expect(
      violations,
      `Arbitrary type utilities found — use the configured scale ` +
        `(text-2xs/text-3xs, tracking-caps/tracking-caps-wide):\n${violations.join('\n')}`,
    ).toEqual([])
  })

  it('no numeric z-index utilities (use the semantic stacking scale)', () => {
    const violations: string[] = []
    for (const file of sourceFiles) {
      const rel = relative(SRC_ROOT, file)
      const lines = readFileSync(file, 'utf8').split('\n')
      lines.forEach((line, i) => {
        if (NUMERIC_Z_UTILITY.test(line)) {
          violations.push(`${rel}:${i + 1}: ${line.trim()}`)
        }
      })
    }
    expect(
      violations,
      `Numeric z-index utilities found — use z-sticky/z-overlay/z-sidebar/z-header/` +
        `z-toast/z-modal (tailwind.config.js):\n${violations.join('\n')}`,
    ).toEqual([])
  })

  it('no raw var(--accent) colour reads (invalid CSS in dark mode — use the brand token)', () => {
    const violations: string[] = []
    for (const file of sourceFiles) {
      const rel = relative(SRC_ROOT, file)
      const lines = readFileSync(file, 'utf8').split('\n')
      lines.forEach((line, i) => {
        if (line.includes('var(--accent')) {
          violations.push(`${rel}:${i + 1}: ${line.trim()}`)
        }
      })
    }
    expect(
      violations,
      `var(--accent) is an HSL triple for Tailwind, not a colour — use the brand token classes:\n${violations.join('\n')}`,
    ).toEqual([])
  })
})
