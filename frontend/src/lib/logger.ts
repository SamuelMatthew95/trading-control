/* eslint-disable no-console -- the one sanctioned console call site; everything
   else routes through createLogger so namespacing and level policy live here. */
/**
 * Namespaced browser logger — the single console gateway for the frontend.
 *
 * Levels:
 * - `debug` / `info`: emitted in development. In production they are silent
 *   unless verbose logging is switched on, either at build time
 *   (`NEXT_PUBLIC_DEBUG_LOGS=true`) or at runtime from the deployed app's
 *   console (`localStorage.setItem('tc:debug', '1')` + reload) — the runtime
 *   switch exists so an operator can capture WebSocket connection diagnostics
 *   without a redeploy.
 * - `warn` / `error`: always emitted; these are operator-facing signals.
 *
 * Never call `console.*` directly outside this module — ESLint enforces it.
 */

export interface Logger {
  debug: (...args: unknown[]) => void
  info: (...args: unknown[]) => void
  warn: (...args: unknown[]) => void
  error: (...args: unknown[]) => void
}

function verboseEnabled(): boolean {
  if (process.env.NODE_ENV !== 'production') return true
  if (process.env.NEXT_PUBLIC_DEBUG_LOGS === 'true') return true
  try {
    return typeof window !== 'undefined' && window.localStorage.getItem('tc:debug') === '1'
  } catch {
    // localStorage can throw in privacy modes — treat as not enabled.
    return false
  }
}

export function createLogger(namespace: string): Logger {
  const tag = `[${namespace}]`
  return {
    debug: (...args) => {
      if (verboseEnabled()) console.debug(tag, ...args)
    },
    info: (...args) => {
      if (verboseEnabled()) console.info(tag, ...args)
    },
    warn: (...args) => console.warn(tag, ...args),
    error: (...args) => console.error(tag, ...args),
  }
}
