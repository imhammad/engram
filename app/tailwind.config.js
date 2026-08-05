/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,ts,jsx,tsx}"],
  theme: {
    extend: {
      colors: {
        canvas: "#F7F5F2",
        surface: "#FFFFFF",
        "surface-muted": "#EDEBE6",
        border: "#E5E2DC",
        ink: "#22201C",
        "ink-muted": "#6B6B65",
        accent: "#0F6B5C",
        "accent-hover": "#0C5548",
      },
      fontFamily: {
        sans: ['"IBM Plex Sans"', "system-ui", "sans-serif"],
        mono: ['"IBM Plex Mono"', "monospace"],
      },
    },
  },
  plugins: [],
};