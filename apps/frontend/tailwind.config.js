/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        parchment: {
          light: '#FDFCF0',
          DEFAULT: '#F5F2E0',
          dark: '#E8E4C9',
        },
        archive: {
          ink: '#2C2C2C',
          paper: '#F1EFE0',
          sepia: '#704214',
        }
      },
      fontFamily: {
        serif: ['"Crimson Text"', 'Georgia', 'serif'],
        mono: ['"IBM Plex Mono"', 'monospace'],
      },
      backgroundImage: {
        'paper-texture': "url('/assets/paper-noise.png')",
      }
    },
  },
  plugins: [],
}
