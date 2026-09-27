import type { Config } from 'tailwindcss'

export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        ground: 'oklch(0.155 0.008 160)',
        panel: 'oklch(0.185 0.009 160)',
        ink: 'oklch(0.94 0.01 160)',
        muted: 'oklch(0.62 0.012 160)',
        line: 'oklch(0.27 0.01 160)',
        accent: 'oklch(0.87 0.17 158)',
        badge: 'oklch(0.9 0.18 100)',
      },
      fontFamily: {
        sans: ['"Hanken Grotesk"', 'system-ui', 'sans-serif'],
        mono: ['"Martian Mono"', 'ui-monospace', 'monospace'],
      },
    },
  },
  plugins: [],
} satisfies Config
