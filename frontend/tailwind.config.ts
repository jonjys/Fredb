import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./app/**/*.{js,ts,jsx,tsx,mdx}"],
  theme: {
    extend: {
      colors: {
        background: "#0b0f14",
        surface: "#121820",
        surfaceAlt: "#1a2230",
        border: "#243040",
        positive: "#22c55e",
        negative: "#ef4444",
        accent: "#3b82f6",
        muted: "#8493a8",
      },
    },
  },
  plugins: [],
};

export default config;
