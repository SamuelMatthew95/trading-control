/** @type {import('tailwindcss').Config} */
module.exports = {
  content: [
    './src/pages/**/*.{js,ts,jsx,tsx,mdx}',
    './src/components/**/*.{js,ts,jsx,tsx,mdx}',
  ],
  darkMode: 'class',
  theme: {
    extend: {
      colors: {
        border: "rgb(var(--border))",
        background: "rgb(var(--background))",
        foreground: "rgb(var(--foreground))",
        card: "rgb(var(--card))",
        "card-foreground": "rgb(var(--card-foreground))",
        popover: "rgb(var(--popover))",
        "popover-foreground": "rgb(var(--popover-foreground))",
        primary: "rgb(var(--primary))",
        "primary-foreground": "rgb(var(--primary-foreground))",
        secondary: "rgb(var(--secondary))",
        "secondary-foreground": "rgb(var(--secondary-foreground))",
        muted: "rgb(var(--muted))",
        "muted-foreground": "rgb(var(--muted-foreground))",
        accent: "rgb(var(--accent))",
        "accent-foreground": "rgb(var(--accent-foreground))",
        destructive: "rgb(var(--destructive))",
        "destructive-foreground": "rgb(var(--destructive-foreground))",
        ring: "rgb(var(--ring))",
        warning: "rgb(var(--warning))",
        success: "rgb(var(--success))",
        info: "rgb(var(--info))",
      },
      fontFamily: {
        sans: ["var(--font-inter)", "system-ui", "sans-serif"],
      },
      letterSpacing: {
        tight: "0.1em",
      },
      boxShadow: {
        sm: '0 1px 3px rgba(0,0,0,0.06)',
      },
    },
  },
  plugins: [],
}
