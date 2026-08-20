/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,jsx}'],
  theme: {
    extend: {
      // PlayStation Blue (#0070d1) reskin — primary-600/700/800 line up with the
      // app's existing bg-*-600/hover:bg-*-700 pattern so `blue` → `primary` is a
      // safe rename, not a restructure. See /home/maeb/Downloads/DESIGN-playstation.md
      colors: {
        primary: {
          50: '#e8f3fc',
          100: '#d1e7f9',
          200: '#a3cff3',
          300: '#75b7ed',
          400: '#3897e2',
          500: '#0070d1', // {colors.primary}
          600: '#0070d1', // default CTA background (matches old bg-blue-600 usage)
          700: '#0064b7', // {colors.primary-pressed} — hover/pressed
          800: '#004d8d', // {colors.primary-active} — deep pressed
          900: '#003a6b',
        },
      },
      fontFamily: {
        sans: ['Inter', 'ui-sans-serif', 'system-ui', 'sans-serif'],
      },
    },
  },
  plugins: [],
}
