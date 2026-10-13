// Personnalisation de l'interface : préférences locales (localStorage, propre à ce poste), appliquées en variables CSS.
import React, { createContext, useContext, useEffect, useState } from "react";

export type Prefs = {
  theme: "nocturne" | "graphite" | "ivoire" | "ambre";
  accent: string | null;          // null = accent du thème
  candles: "aurore" | "classique" | "daltonien";
  density: "compact" | "normal" | "aere";
  rail: "icones" | "libelles";
  chartType: "candles" | "bars" | "line" | "area";
  grid: boolean;
  magnet: boolean;
  activity: boolean;              // panneau d'activité à droite
  motion: boolean;
  favorites: string[];            // écrans épinglés dans la barre du haut
  start: string;                  // écran au lancement
};

export const DEFAULT_PREFS: Prefs = {
  theme: "nocturne", accent: null, candles: "aurore", density: "normal", rail: "libelles", chartType: "candles",
  grid: true, magnet: true, activity: true, motion: true, favorites: ["dash", "lab", "backtests", "genome"], start: "dash",
};

export const THEMES: { id: Prefs["theme"]; name: string; hint: string; sw: string[] }[] = [
  { id: "nocturne", name: "Nocturne", hint: "encre profonde, accent aurore (signature QLab)", sw: ["#0a0d13", "#121826", "#2ee6c5", "#8b7bff"] },
  { id: "graphite", name: "Graphite", hint: "sombre neutre, façon terminal de marché", sw: ["#131722", "#1e222d", "#2962ff", "#787b86"] },
  { id: "ivoire", name: "Ivoire", hint: "clair, lisible en plein jour", sw: ["#f4f5f0", "#ffffff", "#0f7b6c", "#5b4fd6"] },
  { id: "ambre", name: "Ambre", hint: "terminal monochrome ambre", sw: ["#090806", "#14110b", "#ffb000", "#ff6a00"] },
];
export const ACCENTS = ["#2ee6c5", "#8b7bff", "#2962ff", "#ffb000", "#ff5c8a", "#4ade80", "#38bdf8"];
// light : variantes plus sombres pour garder le contraste sur fond clair (thème Ivoire)
export const CANDLES: Record<Prefs["candles"], { name: string; up: string; down: string; light: [string, string] }> = {
  aurore: { name: "Aurore", up: "#2ee6c5", down: "#ff5c8a", light: ["#0e9f87", "#d6336c"] },
  classique: { name: "Classique", up: "#26a69a", down: "#ef5350", light: ["#138a7f", "#d93a37"] },
  daltonien: { name: "Daltonien", up: "#3b82f6", down: "#f59e0b", light: ["#1d64d8", "#c77700"] },
};

const KEY = "qlab.prefs.v1";
function load(): Prefs {
  try { return { ...DEFAULT_PREFS, ...JSON.parse(localStorage.getItem(KEY) ?? "{}") }; } catch { return DEFAULT_PREFS; }
}

const Ctx = createContext<{ p: Prefs; set: (x: Partial<Prefs>) => void; reset: () => void }>({ p: DEFAULT_PREFS, set: () => {}, reset: () => {} });
export const usePrefs = () => useContext(Ctx);

export function PrefsProvider({ children }: { children: React.ReactNode }) {
  const [p, setP] = useState<Prefs>(load);
  useEffect(() => {
    try { localStorage.setItem(KEY, JSON.stringify(p)); } catch { /* stockage indisponible : préférences de session */ }
    const r = document.documentElement;
    r.dataset.theme = p.theme;
    r.dataset.density = p.density;
    r.dataset.motion = p.motion ? "on" : "off";
    const c = CANDLES[p.candles], light = p.theme === "ivoire";
    r.style.setProperty("--up", light ? c.light[0] : c.up);
    r.style.setProperty("--down", light ? c.light[1] : c.down);
    if (p.accent) r.style.setProperty("--acc", p.accent); else r.style.removeProperty("--acc");
  }, [p]);
  return <Ctx.Provider value={{ p, set: (x) => setP((o) => ({ ...o, ...x })), reset: () => setP(DEFAULT_PREFS) }}>{children}</Ctx.Provider>;
}

/** Couleurs résolues du thème courant (pour les canvas de graphiques). */
export function themeColors() {
  const s = getComputedStyle(document.documentElement);
  const v = (k: string) => s.getPropertyValue(k).trim();
  return { bg: v("--panel"), fg: v("--fg"), mut: v("--mut"), bd: v("--bd"), grid: v("--grid"), acc: v("--acc"), acc2: v("--acc2"),
    up: v("--up"), down: v("--down"), warn: v("--warn"), font: v("--font-num") };
}
