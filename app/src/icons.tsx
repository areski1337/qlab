// Jeu d'icônes trait (24×24, currentColor) : aucune dépendance, aucun chargement réseau.
import React from "react";

const P: Record<string, string> = {
  dash: "M3 13h8V3H3zM13 21h8V11h-8zM3 21h8v-6H3zM13 9h8V3h-8z",
  campaigns: "M5 3v18M5 4h11l-2 4 2 4H5",
  data: "M4 6c0-1.7 3.6-3 8-3s8 1.3 8 3-3.6 3-8 3-8-1.3-8-3zM4 6v12c0 1.7 3.6 3 8 3s8-1.3 8-3V6M4 12c0 1.7 3.6 3 8 3s8-1.3 8-3",
  lab: "M9 3v6L4 18a2 2 0 0 0 1.8 3h12.4A2 2 0 0 0 20 18l-5-9V3M8 3h8M7 14h10",
  pareto: "M4 20h16M4 20V4M7 16a1 1 0 1 0 0 .1M11 12a1 1 0 1 0 0 .1M15 9a1 1 0 1 0 0 .1M18 7a1 1 0 1 0 0 .1",
  genome: "M7 3c0 6 10 6 10 12s-10 6-10 6M17 3c0 6-10 6-10 12M8 7h8M8 17h8",
  passport: "M6 3h12v18H6zM9 8h6M9 12h6M9 16h3",
  backtests: "M3 3v18h18M7 15l4-4 3 3 6-6",
  mt5: "M8 9l-4 3 4 3M16 9l4 3-4 3M13 6l-2 12",
  portfolio: "M12 3v9h9A9 9 0 1 1 12 3zM15 3.5A9 9 0 0 1 20.5 9H15z",
  demo: "M2 12s3.6-7 10-7 10 7 10 7-3.6 7-10 7-10-7-10-7zM12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6z",
  tasks: "M9 6h11M9 12h11M9 18h11M4 6l1 1 2-2M4 12l1 1 2-2M4 18l1 1 2-2",
  settings: "M12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6zM19.4 15a1.6 1.6 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.6 1.6 0 0 0-2.7 1.1V21a2 2 0 1 1-4 0v-.1a1.6 1.6 0 0 0-2.7-1.1l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1A1.6 1.6 0 0 0 3.6 15H3a2 2 0 1 1 0-4h.1a1.6 1.6 0 0 0 1.1-2.7l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1A1.6 1.6 0 0 0 9.7 4.4V3a2 2 0 1 1 4 0v.1a1.6 1.6 0 0 0 2.7 1.1l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.6 1.6 0 0 0 1.1 2.7H21a2 2 0 1 1 0 4h-.1z",
  search: "M11 18a7 7 0 1 0 0-14 7 7 0 0 0 0 14zM21 21l-5-5",
  palette: "M12 3a9 9 0 1 0 0 18c1 0 1.5-.8 1.5-1.5 0-.4-.2-.8-.4-1.1-.3-.3-.4-.6-.4-1 0-.8.7-1.4 1.5-1.4H16a5 5 0 0 0 5-5c0-4.4-4-8-9-8zM7.5 11.5h.01M10.5 7.5h.01M15 7.5h.01",
  panel: "M3 4h18v16H3zM15 4v16",
  star: "M12 3l2.8 5.7 6.2.9-4.5 4.4 1 6.2L12 17.3 6.5 20.2l1-6.2L3 9.6l6.2-.9z",
  info: "M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18zM12 11v5M12 8h.01",
  close: "M6 6l12 12M18 6L6 18",
  play: "M7 4l13 8-13 8z",
  pause: "M7 4h4v16H7zM13 4h4v16h-4z",
  bolt: "M13 2L4 14h7l-1 8 9-12h-7z",
  shield: "M12 3l8 3v6c0 5-3.5 8-8 9-4.5-1-8-4-8-9V6z",
  update: "M21 12a9 9 0 0 1-15.5 6.2M3 12A9 9 0 0 1 18.5 5.8M21 4v5h-5M3 20v-5h5",
  empty: "M3 7l9-4 9 4-9 4zM3 7v10l9 4 9-4V7M12 11v10",
};

export function Icon({ n, s = 18, fill }: { n: keyof typeof P | string; s?: number; fill?: boolean }) {
  return (
    <svg width={s} height={s} viewBox="0 0 24 24" fill={fill ? "currentColor" : "none"} stroke="currentColor" strokeWidth={1.7}
      strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d={P[n] ?? P.info} /></svg>
  );
}

/** Marque QLab : hélice stylisée en dégradé aurore. */
export function Logo({ s = 22 }: { s?: number }) {
  return (
    <svg width={s} height={s} viewBox="0 0 32 32" aria-hidden="true">
      <defs><linearGradient id="qlg" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stopColor="var(--acc)" /><stop offset="1" stopColor="var(--acc2)" /></linearGradient></defs>
      <rect x="1" y="1" width="30" height="30" rx="8" fill="none" stroke="url(#qlg)" strokeWidth="2" />
      <path d="M9 22c4-1 6-12 14-12M9 10c4 1 6 12 14 12" fill="none" stroke="url(#qlg)" strokeWidth="2.4" strokeLinecap="round" />
      <circle cx="23" cy="10" r="2" fill="var(--acc)" /><circle cx="23" cy="22" r="2" fill="var(--acc2)" />
    </svg>
  );
}
