/**
 * Design tokens — single source of truth for the utility vocabulary.
 *
 * Every color maps to an HSL CSS variable defined (and theme-flipped) once in
 * src/styles/globals.css. Components never hardcode a semantic hue, a z-index
 * number, a micro font size, or an uppercase tracking value — they use the
 * named tokens below so the whole app re-themes from one place.
 *
 * Surface layering: background (page) < card (panel) < popover (modal).
 */
const config = {
  darkMode: 'class',
  content: [
    './src/pages/**/*.{js,ts,jsx,tsx,mdx}',
    './src/components/**/*.{js,ts,jsx,tsx,mdx}',
    './src/app/**/*.{js,ts,jsx,tsx,mdx}',
  ],
  theme: {
    extend: {
      fontFamily: {
        sans: ['var(--font-sans)', 'Inter', 'system-ui', 'sans-serif'],
        mono: ['var(--font-mono)', 'IBM Plex Mono', 'SFMono-Regular', 'Menlo', 'monospace'],
      },
      // Dense-console micro sizes — the two sanctioned steps below text-xs.
      fontSize: {
        '2xs': ['0.6875rem', { lineHeight: '1rem' }], // 11px — small labels, buttons
        '3xs': ['0.625rem', { lineHeight: '0.875rem' }], // 10px — micro captions, badges
      },
      // Uppercase-label tracking — exactly two steps, no arbitrary values.
      letterSpacing: {
        caps: '0.16em', // labels, table headers, section titles
        'caps-wide': '0.2em', // eyebrows, wordmark, group dividers
      },
      colors: {
        background: 'hsl(var(--background))',
        foreground: 'hsl(var(--foreground) / <alpha-value>)',
        card: 'hsl(var(--card) / <alpha-value>)',
        popover: 'hsl(var(--popover) / <alpha-value>)',
        border: 'hsl(var(--border))',
        ring: 'hsl(var(--ring))',
        muted: {
          DEFAULT: 'hsl(var(--muted) / <alpha-value>)',
          foreground: 'hsl(var(--muted-foreground) / <alpha-value>)',
        },
        // Brand/interactive accent (logo, active nav, evolution/challenger UI).
        brand: 'hsl(var(--primary) / <alpha-value>)',
        // Semantic Tone tokens — light/dark values flip once in src/styles/globals.css
        success: 'hsl(var(--success) / <alpha-value>)',
        danger: 'hsl(var(--danger) / <alpha-value>)',
        warning: 'hsl(var(--warning) / <alpha-value>)',
      },
      borderColor: {
        // Hover/emphasis border — one step stronger than the default border.
        strong: 'hsl(var(--border-strong))',
      },
      borderRadius: {
        lg: 'var(--radius)',
        md: 'calc(var(--radius) - 2px)',
        sm: 'calc(var(--radius) - 4px)',
      },
      boxShadow: {
        card: 'var(--shadow-card)',
        modal: 'var(--shadow-modal)',
      },
      // Stacking scale — always use these, never numeric z utilities.
      zIndex: {
        sticky: '10', // sticky table headers
        overlay: '30', // sidebar backdrop
        sidebar: '40',
        header: '50',
        toast: '60', // floating status indicators
        modal: '70',
      },
      maxHeight: {
        modal: '80vh',
      },
      keyframes: {
        'fade-in': {
          from: { opacity: '0' },
          to: { opacity: '1' },
        },
        'scale-in': {
          from: { opacity: '0', transform: 'translateY(4px) scale(0.98)' },
          to: { opacity: '1', transform: 'translateY(0) scale(1)' },
        },
      },
      animation: {
        'fade-in': 'fade-in 120ms ease-out',
        'scale-in': 'scale-in 150ms ease-out',
      },
    },
  },
  plugins: [],
}

module.exports = config
