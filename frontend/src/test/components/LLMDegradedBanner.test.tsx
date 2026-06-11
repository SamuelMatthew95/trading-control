import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'

import { LLMDegradedBanner } from '@/components/dashboard/LLMDegradedBanner'
import { useLlmHealth, type LLMHealthData } from '@/lib/llm-health'

// Mock only the hook; keep the real LLMStatus constants (spread of the module).
vi.mock('@/lib/llm-health', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/lib/llm-health')>()
  return { ...actual, useLlmHealth: vi.fn() }
})

const mockedUseLlmHealth = vi.mocked(useLlmHealth)

function health(overrides: Partial<LLMHealthData>): {
  data: LLMHealthData | null
  error: string | null
} {
  return {
    // Only the fields the banner reads need to be real; cast covers the rest.
    data: {
      status: 'degraded',
      provider: 'gemini',
      active_provider: 'gemini',
      success_rate_pct: 60,
      llm_fallback_enabled: false,
      ...overrides,
    } as LLMHealthData,
    error: null,
  }
}

describe('LLMDegradedBanner', () => {
  beforeEach(() => vi.clearAllMocks())

  it('shows a warning banner when the LLM is degraded', () => {
    mockedUseLlmHealth.mockReturnValue(health({ status: 'degraded' }))
    render(<LLMDegradedBanner />)
    const alert = screen.getByRole('alert')
    expect(alert.className).toContain('warning')
    expect(alert.textContent).toContain('degraded')
    expect(alert.textContent).toContain('fails closed')
  })

  it('shows an error banner in fallback mode when the LLM is down', () => {
    mockedUseLlmHealth.mockReturnValue(health({ status: 'down' }))
    render(<LLMDegradedBanner />)
    const alert = screen.getByRole('alert')
    expect(alert.className).toContain('danger')
    expect(alert.textContent).toContain('fallback mode')
  })

  it('notes that cloud fallback is enabled when configured', () => {
    mockedUseLlmHealth.mockReturnValue(health({ status: 'degraded', llm_fallback_enabled: true }))
    render(<LLMDegradedBanner />)
    expect(screen.getByRole('alert').textContent).toContain('Cloud fallback is enabled')
  })

  it('explains the downstream cascade (why learning agents look idle)', () => {
    mockedUseLlmHealth.mockReturnValue(health({ status: 'degraded' }))
    render(<LLMDegradedBanner />)
    const alert = screen.getByRole('alert')
    expect(alert.textContent).toContain('learning agents')
    expect(alert.textContent).toContain('wiring is intact')
  })

  it('renders nothing while the LLM is live', () => {
    mockedUseLlmHealth.mockReturnValue(health({ status: 'live' }))
    render(<LLMDegradedBanner />)
    expect(screen.queryByRole('alert')).toBeNull()
  })

  it('renders nothing when status is unknown (no calls yet) or data is absent', () => {
    mockedUseLlmHealth.mockReturnValue(health({ status: 'unknown' }))
    const { rerender } = render(<LLMDegradedBanner />)
    expect(screen.queryByRole('alert')).toBeNull()

    mockedUseLlmHealth.mockReturnValue({ data: null, error: null })
    rerender(<LLMDegradedBanner />)
    expect(screen.queryByRole('alert')).toBeNull()
  })
})
