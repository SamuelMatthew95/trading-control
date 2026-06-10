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
 *      invalid CSS in dark mode. The brand colour is `var(--brand)`.
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
  /\b(?:text|bg|border|ring|from|via|to|fill|stroke|outline|decoration|divide|shadow|accent|caret)-(?:emerald|green|rose|red|amber|yellow)-\d{2,3}\b/

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

  it('no raw var(--accent) colour reads (invalid CSS in dark mode — use var(--brand))', () => {
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
      `var(--accent) is an HSL triple for Tailwind, not a colour — use var(--brand):\n${violations.join('\n')}`,
    ).toEqual([])
  })
})
