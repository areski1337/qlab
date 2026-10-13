// Tiroir « Personnaliser » : thème, accent, couleurs de bougies, densité, graphiques, écrans favoris, écran de départ.
import React from "react";
import { ACCENTS, CANDLES, DEFAULT_PREFS, Prefs, THEMES, usePrefs } from "./prefs";
import { Icon } from "./icons";
import { Seg } from "./ui";
import { SCREENS } from "./main";

export function Personalize({ onClose }: { onClose: () => void }) {
  const { p, set, reset } = usePrefs();
  const fav = (k: string, on: boolean) => set({ favorites: on ? [...p.favorites.filter((x) => x !== k), k] : p.favorites.filter((x) => x !== k) });
  return (
    <div className="overlay" style={{ padding: 0, background: "transparent", backdropFilter: "none" }} onMouseDown={onClose}>
      <aside className="drawer" role="dialog" aria-label="Personnaliser l'interface" onMouseDown={(e) => e.stopPropagation()}>
        <header><Icon n="palette" /><h2>Personnaliser</h2>
          <button className="btn ghost" onClick={reset} title="Revenir aux réglages par défaut">Réinitialiser</button>
          <button className="iconbtn" onClick={onClose} aria-label="Fermer"><Icon n="close" /></button></header>
        <div className="body">
          <section>
            <h3>Thème</h3>
            <div className="themes">
              {THEMES.map((t) => <button key={t.id} className={p.theme === t.id ? "on" : ""} aria-pressed={p.theme === t.id} onClick={() => set({ theme: t.id })}>
                <div className="sw">{t.sw.map((c) => <i key={c} style={{ background: c }} />)}</div>
                <b>{t.name}</b><small>{t.hint}</small></button>)}
            </div>
          </section>
          <section>
            <h3>Couleur d'accent</h3>
            <div className="swatches">
              <button className={!p.accent ? "on" : ""} title="Accent du thème" aria-label="Accent du thème" onClick={() => set({ accent: null })}
                style={{ background: "conic-gradient(var(--acc), var(--acc2), var(--acc))" }} />
              {ACCENTS.map((c) => <button key={c} className={p.accent === c ? "on" : ""} aria-label={`Accent ${c}`} style={{ background: c }} onClick={() => set({ accent: c })} />)}
              <input type="color" aria-label="Accent personnalisé" value={p.accent ?? "#2ee6c5"} onChange={(e) => set({ accent: e.target.value })} />
            </div>
          </section>
          <section>
            <h3>Hausse / baisse</h3>
            <div className="swatches" style={{ gap: 10 }}>
              {(Object.keys(CANDLES) as Prefs["candles"][]).map((k) => <button key={k} onClick={() => set({ candles: k })} aria-pressed={p.candles === k}
                className={"btn" + (p.candles === k ? " primary" : "")} style={{ width: "auto", height: "auto", borderRadius: 6 }}>
                <i style={{ width: 10, height: 14, background: CANDLES[k].up, display: "inline-block", borderRadius: 2 }} />
                <i style={{ width: 10, height: 14, background: CANDLES[k].down, display: "inline-block", borderRadius: 2 }} />{CANDLES[k].name}</button>)}
            </div>
          </section>
          <section>
            <h3>Graphiques de prix</h3>
            <div className="row" style={{ alignItems: "center" }}>
              <Seg label="Type de graphique" value={p.chartType} onChange={(v) => set({ chartType: v })}
                options={[["candles", "Bougies"], ["bars", "Barres"], ["line", "Ligne"], ["area", "Aire"]]} />
              <label><input type="checkbox" checked={p.grid} onChange={(e) => set({ grid: e.target.checked })} /> Grille</label>
              <label><input type="checkbox" checked={p.magnet} onChange={(e) => set({ magnet: e.target.checked })} /> Réticule aimanté</label>
            </div>
          </section>
          <section>
            <h3>Disposition</h3>
            <div className="row" style={{ alignItems: "center" }}>
              <Seg label="Densité" value={p.density} onChange={(v) => set({ density: v })} options={[["compact", "Compacte"], ["normal", "Normale"], ["aere", "Aérée"]]} />
              <Seg label="Rail" value={p.rail} onChange={(v) => set({ rail: v })} options={[["libelles", "Icônes + libellés"], ["icones", "Icônes"]]} />
            </div>
            <div className="row" style={{ alignItems: "center", marginTop: 8 }}>
              <label><input type="checkbox" checked={p.activity} onChange={(e) => set({ activity: e.target.checked })} /> Panneau d'activité</label>
              <label><input type="checkbox" checked={p.motion} onChange={(e) => set({ motion: e.target.checked })} /> Animations</label>
            </div>
          </section>
          <section>
            <h3>Écrans : favoris (barre du haut) et démarrage</h3>
            <div className="checks">
              {SCREENS.map((s) => <div key={s.k} style={{ display: "flex", alignItems: "center", gap: 8 }}>
                <button className="iconbtn" aria-pressed={p.favorites.includes(s.k)} title="Favori" onClick={() => fav(s.k, !p.favorites.includes(s.k))}
                  style={{ color: p.favorites.includes(s.k) ? "var(--warn)" : undefined }}><Icon n="star" s={16} fill={p.favorites.includes(s.k)} /></button>
                <Icon n={s.icon} s={16} /><span style={{ flex: 1 }}>{s.label}</span>
                <label className="muted" style={{ display: "inline-flex", gap: 4, alignItems: "center" }}>
                  <input type="radio" name="start" checked={p.start === s.k} onChange={() => set({ start: s.k })} />départ</label>
              </div>)}
            </div>
          </section>
          <section>
            <h3>Raccourcis</h3>
            <dl className="kv">
              <dt><span className="kbd">Ctrl K</span></dt><dd>palette : écrans, campagnes, révisions, thèmes</dd>
              <dt><span className="kbd">Alt 1…9</span></dt><dd>aller à l'écran n</dd>
              <dt><span className="kbd">Ctrl J</span></dt><dd>panneau d'activité</dd>
              <dt><span className="kbd">Ctrl B</span></dt><dd>rail icônes / libellés</dd>
              <dt><span className="kbd">Ctrl ,</span></dt><dd>ce panneau</dd>
            </dl>
            <p className="muted">Préférences propres à ce poste (stockage local). Défaut : thème {THEMES.find((t) => t.id === DEFAULT_PREFS.theme)?.name}.</p>
          </section>
        </div>
      </aside>
    </div>
  );
}
