/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        ink: { 950: "#0b0e14", 900: "#0f121a", 850: "#121620", 800: "#151a24", 700: "#1b2130", 600: "#232a38", 500: "#2f3849" },
        fg: { DEFAULT: "#e6e9ef", 2: "#9aa3b5", 3: "#646d80" },
        blue: { DEFAULT: "#3b82f6" }, emerald: { DEFAULT: "#10b981" }, amber: { DEFAULT: "#f59e0b" },
        ruby: { DEFAULT: "#ef4444" }, violet: { DEFAULT: "#8b5cf6" },
      },
      fontFamily: {
        sans: ["Inter", "Segoe UI", "system-ui", "sans-serif"],
        mono: ["JetBrains Mono", "Cascadia Mono", "Consolas", "ui-monospace", "monospace"],
      },
      boxShadow: { glow: "0 0 0 1px rgba(59,130,246,.25), 0 8px 30px -12px rgba(59,130,246,.45)" },
    },
  },
  plugins: [],
};
