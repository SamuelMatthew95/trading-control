/* eslint-disable @typescript-eslint/no-explicit-any */
import '@testing-library/jest-dom'
import React from 'react'
import { vi } from 'vitest'

// jsdom has no ResizeObserver, which recharts' ResponsiveContainer requires.
// Without it, any component that renders a chart (e.g. the terminal PriceChart)
// throws "ResizeObserver is not defined" on mount. Provide a no-op stub.
class ResizeObserverStub {
  observe() {}
  unobserve() {}
  disconnect() {}
}
if (!('ResizeObserver' in globalThis)) {
  ;(globalThis as unknown as { ResizeObserver: typeof ResizeObserverStub }).ResizeObserver = ResizeObserverStub
}

vi.mock('next/navigation', () => ({
  useRouter: () => ({
    push: vi.fn(),
    replace: vi.fn(),
    back: vi.fn(),
    forward: vi.fn(),
    refresh: vi.fn(),
    prefetch: vi.fn()
  }),
  usePathname: () => '/dashboard',
  useSearchParams: () => new URLSearchParams()
}))

vi.mock('next/image', () => ({
  default: ({ src, alt, ...props }: any) => {
    // eslint-disable-next-line @next/next/no-img-element
    return React.createElement('img', { src, alt, ...props })
  }
}))

const originalError = console.error
beforeAll(() => {
  console.error = (...args: any[]) => {
    if (typeof args[0] === 'string' && args[0].includes('Warning:')) return
    originalError.call(console, ...args)
  }
})

afterAll(() => {
  console.error = originalError
})
