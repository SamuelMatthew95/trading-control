import { describe, it, expect } from 'vitest'
import { readFileSync, readdirSync, statSync } from 'fs'
import { join } from 'path'
import {
  CHIP_BASE,
  CHIP_BASE_BOLD,
  INNER_TILE,
  ROW_DIVIDER,
  TRACE_BUTTON,
} from '../dashboard'

/**
 * Guardrail tests for the dashboard styling rules.
 *
 * The dashboard refactor extracted every repeated Tailwind chain into a named
 * constant in `lib/styles/dashboard.ts`. These tests fail if anyone
 * re-introduces a banned inline class chain anywhere in the section /
 * dashboard component tree.
 *
 * To add a new forbidden pattern: add it to BANNED_PATTERNS below.
 */

const ROOT = join(__dirname, '..', '..', '..')
const FRONTEND_ROOT = join(ROOT, '..')
const SECTIONS_DIR = join(ROOT, 'components', 'dashboard', 'sections')

interface BannedPattern {
  description: string
  /** Substring of an inline className that signals an un-extracted chain. */
  needle: string
  /** Where to look. */
  dirs: string[]
  /** Files exempt from the check (relative to ROOT). */
  exempt?: string[]
}

const BANNED_PATTERNS: BannedPattern[] = [
  {
    description: 'INNER_TILE pattern must come from lib/styles, not be inlined',
    needle: 'rounded-[6px] border border-slate-200 p-3 dark:border-slate-800',
    dirs: [SECTIONS_DIR],
  },
  {
    description: 'TRACE_BUTTON pattern must come from lib/styles',
    needle:
      "rounded-[4px] px-1.5 py-0.5 text-[10px] font-mono text-slate-500 transition-colors hover:bg-slate-100",
    dirs: [SECTIONS_DIR],
  },
  {
    description: 'EVENT_ROW pattern must come from lib/styles',
    needle:
      'flex items-center justify-between rounded-[6px] border border-slate-200 px-3 py-2 dark:border-slate-800',
    dirs: [SECTIONS_DIR],
  },
  {
    description: 'space-y-4 stack should come from STACK constant',
    needle: 'className="space-y-4"',
    dirs: [SECTIONS_DIR],
  },
]

function readAllTsx(dir: string): Array<{ file: string; content: string }> {
  const out: Array<{ file: string; content: string }> = []
  for (const name of readdirSync(dir)) {
    if (name === '__tests__') continue
    const full = join(dir, name)
    const stat = statSync(full)
    if (stat.isDirectory()) {
      out.push(...readAllTsx(full))
      continue
    }
    if (!name.endsWith('.tsx') && !name.endsWith('.ts')) continue
    out.push({ file: full, content: readFileSync(full, 'utf8') })
  }
  return out
}

describe('dashboard style guardrails', () => {
  for (const pattern of BANNED_PATTERNS) {
    it(pattern.description, () => {
      const offenders: string[] = []
      for (const dir of pattern.dirs) {
        for (const { file, content } of readAllTsx(dir)) {
          if (pattern.exempt?.some((e) => file.endsWith(e))) continue
          if (content.includes(pattern.needle)) {
            offenders.push(file.replace(ROOT, '...'))
          }
        }
      }
      expect(
        offenders,
        `Inline pattern reintroduced — extract to lib/styles:\n  ${pattern.needle}\n  in: ${offenders.join('\n  in: ')}`,
      ).toEqual([])
    })
  }
})

describe('lib/styles exports are consistent', () => {
  it('INNER_TILE encodes the canonical inner-tile pattern', () => {
    expect(INNER_TILE).toContain('rounded-[6px]')
    expect(INNER_TILE).toContain('border-slate-200')
  })
  it('CHIP_BASE and CHIP_BASE_BOLD share the same shape but differ in weight', () => {
    expect(CHIP_BASE).toContain('font-semibold')
    expect(CHIP_BASE_BOLD).toContain('font-bold')
  })
  it('ROW_DIVIDER does not include the first-child reset', () => {
    expect(ROW_DIVIDER).not.toContain('first:border-t-0')
  })
  it('TRACE_BUTTON includes hover transition', () => {
    expect(TRACE_BUTTON).toContain('hover:bg-slate-100')
    expect(TRACE_BUTTON).toContain('transition-colors')
  })
})

describe('layout and high-level files use the styles module', () => {
  it('app/dashboard/layout.tsx imports from lib/styles', () => {
    const layoutPath = join(FRONTEND_ROOT, 'app', 'dashboard', 'layout.tsx')
    // The test runner CWD is the frontend root; resolve relative to ROOT/..
    let content: string
    try {
      content = readFileSync(layoutPath, 'utf8')
    } catch {
      content = readFileSync(join(ROOT, 'app', 'dashboard', 'layout.tsx'), 'utf8')
    }
    expect(content).toContain("from '@/lib/styles'")
  })

  it('NotificationFeed.tsx imports from lib/styles', () => {
    const file = readFileSync(
      join(ROOT, 'components', 'dashboard', 'NotificationFeed.tsx'),
      'utf8',
    )
    expect(file).toContain("from '@/lib/styles'")
  })
})
