import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'
import { resolve } from 'path'

export default defineConfig({
  plugins: [react()],
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./src/test/setup.ts'],
    coverage: {
      provider: 'v8',
      reporter: ['text', 'lcov', 'html'],
      include: [
        'src/app/dashboard/DashboardView.tsx',
        'src/components/layout/Header.tsx',
        'src/utils/dashboard.ts',
        'src/types/dashboard.ts'
      ],
      exclude: [
        'node_modules/**',
        '.next/**',
        'src/test/**',
        '**/*.config.*',
        '**/types/**',
        '**/*.d.ts'
      ],
      thresholds: {
        lines: 50,
        functions: 60,
        branches: 40,
        statements: 50
      }
    }
  },
  resolve: {
    alias: {
      '@': resolve(__dirname, './src')
    }
  }
})
