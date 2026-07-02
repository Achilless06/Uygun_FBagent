/**
 * Tailwind build config — replaces the former CDN runtime config that lived
 * inline in base.html (CDN was ~350KB of JS on every first paint).
 *
 * Rebuild after adding/changing classes in templates or route .py files:
 *   npx tailwindcss@3.4.16 -c tailwind.config.js \
 *     -i src/web/static/css/input.css -o src/web/static/css/tw.css --minify
 *
 * Keep the version pinned to 3.4.16 (matches the previously pinned CDN) so
 * utility behavior never drifts silently.
 */
module.exports = {
  darkMode: 'class',
  content: [
    './src/web/templates/**/*.html',
    './src/web/routes/**/*.py',
    './src/web/i18n/**/*.py',
  ],
  theme: {
    extend: {
      colors: {
        'uygun-red':   '#BC1215',
        'uygun-dark':  '#7A0C0E',
        'uygun-black': '#0F0F0F',
        'uygun-grey':  '#555555',
        'uygun-light': '#F5F5F5',
      },
      fontFamily: {
        sans: ['Inter', 'Noto Sans Georgian', 'system-ui', 'sans-serif'],
      },
      letterSpacing: {
        tighter: '-0.04em',
        tight:   '-0.025em',
      },
      boxShadow: {
        'soft':  '0 1px 2px rgba(0,0,0,0.06), 0 8px 32px rgba(0,0,0,0.06)',
        'hover': '0 1px 2px rgba(0,0,0,0.08), 0 24px 64px rgba(0,0,0,0.10)',
        'card':  '0 0 0 1px rgba(0,0,0,0.06), 0 4px 24px rgba(0,0,0,0.06)',
      },
      transitionTimingFunction: {
        'smooth': 'cubic-bezier(0.25, 0.46, 0.45, 0.94)',
      },
    },
  },
};
