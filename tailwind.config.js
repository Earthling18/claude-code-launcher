/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        // Surfaces
        'surface-base': 'var(--surface-base)',
        'surface-1':    'var(--surface-1)',
        'surface-2':    'var(--surface-2)',
        'surface-3':    'var(--surface-3)',
        'surface-input':'var(--surface-input)',
        // Lines
        'line':        'var(--line-soft)',
        'line-strong': 'var(--line-strong)',
        // Text
        'text-primary':   'var(--text-primary)',
        'text-secondary': 'var(--text-secondary)',
        'text-tertiary':  'var(--text-tertiary)',
        'text-disabled':  'var(--text-disabled)',
        // Accent
        'accent':        'var(--accent)',
        'accent-strong': 'var(--accent-strong)',
        'accent-deep':   'var(--accent-deep)',
        // Modes
        'mode-claude': 'var(--mode-claude)',
        'mode-codex':  'var(--mode-codex)',
        'mode-custom': 'var(--mode-custom)',
        // States
        'ok':    'var(--ok)',
        'warn':  'var(--warn)',
        'error': 'var(--error)',
        'info':  'var(--info)',
      },
      fontFamily: {
        sans: ['var(--font-sans)'],
        mono: ['var(--font-mono)'],
      },
      borderRadius: {
        DEFAULT: 'var(--radius)',
        sm: 'var(--radius-sm)',
        lg: 'var(--radius-lg)',
      },
      transitionTimingFunction: {
        'out-soft': 'var(--ease-out)',
        'spring':   'var(--ease-spring)',
      },
    },
  },
  plugins: [],
  darkMode: 'class',
}
