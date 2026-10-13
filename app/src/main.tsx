import React, { createContext, useContext, useEffect, useMemo, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import "./styles.css";
import { Dashboard } from "./screens/Dashboard";
import { Campaigns, CampaignLab, Pareto } from "./screens/Campaigns";
import { Data } from "./screens/Data";
import { GenomeExplorer, Passport, Backtests } from "./screens/Genome";
import { Mt5 } from "./screens/Mt5";
import { Portfolio, Demo } from "./screens/Portfolio";
import { Tasks, Settings } from "./screens/System";
import { Personalize } from "./personalize";
import { PrefsProvider, THEMES, usePrefs } from "./prefs";
import { Icon, Logo } from "./icons";
import { Badge, fmt, useApi } from "./ui";

export type Nav = { screen: string; rev?: string; campaign?: string };
export const NavCtx = createContext<{ nav: Nav; go: (n: Nav) => void }>({ nav: { screen: "dash" }, go: () => {} });
export const useNav = () => useContext(NavCtx);

export const SCREENS: { k: string; label: string; short: string; icon: string; group: string; C: React.FC }[] = [
  { k: "dash", label: "Tableau de bord", short: "Accueil", icon: "dash", group: "Pilotage", C: Dashboard },
  { k: "campaigns", label: "Campagnes", short: "Campagnes", icon: "campaigns", group: "Recherche", C: Campaigns },
  { k: "data", label: "Données & qualité", short: "Données", icon: "data", group: "Recherche", C: Data },
  { k: "lab", label: "Laboratoire génétique", short: "Labo", icon: "lab", group: "Recherche", C: CampaignLab },
  { k: "pareto", label: "Comparaison & Pareto", short: "Pareto", icon: "pareto", group: "Recherche", C: Pareto },
  { k: "genome", label: "Génome & validation", short: "Génome", icon: "genome", group: "Validation", C: GenomeExplorer },
  { k: "backtests", label: "Backtests & transactions", short: "Backtest", icon: "backtests", group: "Validation", C: Backtests },
  { k: "passport", label: "Passeport", short: "Passeport", icon: "passport", group: "Validation", C: Passport },
  { k: "mt5", label: "MQL5 & parité MT5", short: "MT5", icon: "mt5", group: "Validation", C: Mt5 },
  { k: "portfolio", label: "Portefeuilles", short: "Portefeuille", icon: "portfolio", group: "Exploitation", C: Portfolio },
  { k: "demo", label: "Surveillance démo", short: "Démo", icon: "demo", group: "Exploitation", C: Demo },
  { k: "tasks", label: "Tâches & journaux", short: "Tâches", icon: "tasks", group: "Système", C: Tasks },
  { k: "settings", label: "Paramètres & sauvegardes", short: "Paramètres", icon: "settings", group: "Système", C: Settings },
];

function App() {
  const { p, set } = usePrefs();
  const [nav, setNav] = useState<Nav>({ screen: SCREENS.some((s) => s.k === p.start) ? p.start : "dash" });
  const [engine, setEngine] = useState<{ state: "starting" | "ready" | "failed" | "stopped"; detail?: string }>({ state: "starting" });
  const [upd, setUpd] = useState<string | null>(null);
  const [events, setEvents] = useState<{ ts: string; text: string; err?: boolean }[]>([]);
  const [palette, setPalette] = useState(false);
  const [drawer, setDrawer] = useState(false);
  const go = (n: Nav) => setNav(n);

  useEffect(() => window.qlab.onEvent((ev) => {
    if (ev.type === "engine.ready") setEngine({ state: "ready" });
    if (ev.type === "engine.failed") setEngine({ state: "failed", detail: ev.error });
    if (ev.type === "engine.exited") setEngine({ state: "stopped", detail: `code ${ev.code}` });
    if (ev.type === "update.available") setUpd(ev.version);
    if (ev.type === "task.updated" || ev.type?.startsWith("engine.")) {
      const t = ev.task ?? {};
      const text = ev.type === "task.updated" ? `${t.kind ?? "tâche"} → ${t.state ?? "maj"}${t.progress != null ? ` ${fmt(t.progress * 100, 0)} %` : ""}` : ev.type;
      setEvents((e) => [{ ts: (ev.ts ?? new Date().toISOString()).slice(11, 19), text, err: t.state === "failed" || ev.type === "engine.failed" }, ...e].slice(0, 40));
    }
  }), []);
  useEffect(() => { window.qlab.request("GET", "/api/v1/health").then((r) => r.status === 200 && setEngine({ state: "ready" })); }, []);

  useEffect(() => {
    const h = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") { e.preventDefault(); setPalette((x) => !x); }
      else if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "j") { e.preventDefault(); set({ activity: !p.activity }); }
      else if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "b") { e.preventDefault(); set({ rail: p.rail === "icones" ? "libelles" : "icones" }); }
      else if ((e.ctrlKey || e.metaKey) && e.key === ",") { e.preventDefault(); setDrawer((x) => !x); }
      else if (e.altKey && /^[1-9]$/.test(e.key)) { e.preventDefault(); const s = SCREENS[Number(e.key) - 1]; if (s) setNav((n) => ({ ...n, screen: s.k })); }
      else if (e.key === "Escape") { setPalette(false); setDrawer(false); }
    };
    const open = () => setDrawer(true);
    window.addEventListener("keydown", h);
    window.addEventListener("qlab:personalize", open);
    return () => { window.removeEventListener("keydown", h); window.removeEventListener("qlab:personalize", open); };
  }, [p.activity, p.rail]);

  const cur = SCREENS.find((s) => s.k === nav.screen) ?? SCREENS[0];
  const Cur = cur.C;
  const groups = [...new Set(SCREENS.map((s) => s.group))];
  return (
    <NavCtx.Provider value={{ nav, go }}>
      <div className="shell" style={{ gridTemplateColumns: `auto 1fr ${p.activity ? "300px" : "0px"}` }}>
        <header className="top">
          <div className="logo"><Logo /><span><b>QLab</b></span></div>
          <div className="quick" role="tablist" aria-label="Écrans favoris">
            {p.favorites.map((k) => SCREENS.find((s) => s.k === k)).filter(Boolean).map((s) => (
              <button key={s!.k} role="tab" aria-selected={nav.screen === s!.k} className={nav.screen === s!.k ? "on" : ""} onClick={() => go({ ...nav, screen: s!.k })}>
                <Icon n={s!.icon} s={15} />{s!.short}</button>))}
          </div>
          <span className="grow" />
          <button className="search" onClick={() => setPalette(true)} aria-label="Rechercher (Ctrl+K)"><Icon n="search" s={15} />Aller à…<span className="grow" /><span className="kbd">Ctrl K</span></button>
          {upd && <button className="pill upd" onClick={() => go({ screen: "settings" })}><Icon n="update" s={13} />v{upd}</button>}
          <span className="pill env" title="Environnement : recherche et simulation">Recherche / Simulation</span>
          <span className="pill off" title="Aucun ordre réel ne peut être envoyé par QLab">Réel : off</span>
          <button className={"iconbtn" + (p.activity ? " on" : "")} title="Panneau d'activité (Ctrl+J)" aria-pressed={p.activity} onClick={() => set({ activity: !p.activity })}><Icon n="panel" /></button>
          <button className="iconbtn" title="Personnaliser (Ctrl+,)" onClick={() => setDrawer(true)}><Icon n="palette" /></button>
        </header>

        <nav className={"rail " + p.rail} aria-label="Écrans">
          {groups.map((g, gi) => <React.Fragment key={g}>
            {gi > 0 && <div className="sep" />}
            {SCREENS.filter((s) => s.group === g).map((s) => {
              const i = SCREENS.indexOf(s);
              return <button key={s.k} className={nav.screen === s.k ? "on" : ""} title={`${s.label}${i < 9 ? ` (Alt+${i + 1})` : ""}`}
                aria-current={nav.screen === s.k ? "page" : undefined} onClick={() => go({ ...nav, screen: s.k })}>
                <Icon n={s.icon} /><span className="lbl">{s.label}</span>{i < 9 && <span className="k">{i + 1}</span>}</button>;
            })}
          </React.Fragment>)}
        </nav>

        <main>{engine.state === "failed" ? <EngineDown detail={engine.detail} /> : <Cur key={cur.k} />}</main>

        {p.activity && <Activity events={events} />}

        <footer className="status">
          <span><i className={"dot " + (engine.state === "ready" ? "ok" : engine.state === "starting" ? "run" : "err")} />
            moteur {engine.state === "ready" ? "prêt" : engine.state === "starting" ? "démarrage…" : engine.state === "failed" ? "en échec" : "arrêté"}</span>
          <StatusHealth ready={engine.state === "ready"} />
          {nav.campaign && <span>campagne {nav.campaign}</span>}
          {nav.rev && <span>révision {nav.rev}</span>}
          <span className="grow" />
          <span>{THEMES.find((t) => t.id === p.theme)?.name}</span>
          <Clock />
        </footer>
      </div>
      {palette && <Palette onClose={() => setPalette(false)} onDrawer={() => { setPalette(false); setDrawer(true); }} />}
      {drawer && <Personalize onClose={() => setDrawer(false)} />}
    </NavCtx.Provider>
  );
}

function StatusHealth({ ready }: { ready: boolean }) {
  const h = useApi<any>(ready ? "/health" : null, [ready], true);
  if (!h.data) return null;
  return <>
    <span>worker {h.data.worker_alive ? "actif" : "inactif"}</span>
    <span>schéma v{h.data.schema}</span>
    <span>disque {fmt(h.data.disk_free_mb / 1024, 0)} Go</span>
    <span>MT5 {h.data.mt5?.terminal_found ? "✓" : "✗"}</span>
  </>;
}

function Clock() {
  const [t, setT] = useState(new Date());
  useEffect(() => { const i = setInterval(() => setT(new Date()), 1000); return () => clearInterval(i); }, []);
  return <span>{t.toISOString().slice(11, 19)} UTC</span>;
}

function Activity({ events }: { events: { ts: string; text: string; err?: boolean }[] }) {
  const { nav, go } = useNav();
  const t = useApi<any[]>("/tasks", [], true);
  const active = t.data?.filter((x) => ["queued", "validating", "running", "paused"].includes(x.state)) ?? [];
  return (
    <aside className="side" aria-label="Activité">
      <h4>Tâches actives · {active.length}</h4>
      <div className="feed">
        {active.length === 0 && <div className="muted" style={{ padding: "0 8px" }}>Aucune tâche active.</div>}
        {active.map((x) => (
          <div key={x.id} className="it" onClick={() => go({ ...nav, screen: x.kind === "campaign" ? "lab" : "tasks" })}>
            <div className="t"><b>{x.kind}</b><Badge s={x.state} /></div>
            <div className="progress" style={{ marginTop: 6 }}><i style={{ width: `${(x.progress ?? 0) * 100}%` }} /></div>
            <div className="muted" style={{ fontSize: 11, marginTop: 4, fontFamily: "var(--font-num)" }}>{fmt((x.progress ?? 0) * 100, 0)} % · {x.id}</div>
          </div>))}
      </div>
      <h4>Flux d'événements</h4>
      <div className="feed">
        {events.length === 0 && <div className="muted" style={{ padding: "0 8px" }}>En attente d'événements…</div>}
        {events.map((e, i) => <div key={i} className={"ev" + (e.err ? " err" : "")}>{e.ts} {e.text}</div>)}
      </div>
    </aside>
  );
}

type Cmd = { id: string; label: string; group: string; icon: string; run: () => void };

function Palette({ onClose, onDrawer }: { onClose: () => void; onDrawer: () => void }) {
  const { nav, go } = useNav();
  const { p, set } = usePrefs();
  const [q, setQ] = useState("");
  const [i, setI] = useState(0);
  const camps = useApi<any[]>("/campaigns");
  const revs = useApi<any[]>("/genomes?limit=300");
  const inp = useRef<HTMLInputElement>(null);
  useEffect(() => inp.current?.focus(), []);
  const cmds: Cmd[] = useMemo(() => {
    const c: Cmd[] = SCREENS.map((s) => ({ id: "s" + s.k, label: s.label, group: "Écran", icon: s.icon, run: () => go({ ...nav, screen: s.k }) }));
    if (/^rev_/.test(q.trim())) c.unshift({ id: "rev", label: `Ouvrir la révision ${q.trim()}`, group: "Révision", icon: "genome", run: () => go({ ...nav, screen: "genome", rev: q.trim() }) });
    for (const x of camps.data ?? []) c.push({ id: "c" + x.id, label: `${x.name} · ${x.id}`, group: "Campagne", icon: "lab", run: () => go({ ...nav, screen: "lab", campaign: x.id }) });
    for (const x of revs.data ?? []) c.push({ id: "r" + x.id, label: `${x.id} · ${x.status}`, group: "Révision", icon: "genome", run: () => go({ ...nav, screen: "genome", rev: x.id }) });
    for (const t of THEMES) c.push({ id: "t" + t.id, label: `Thème : ${t.name}`, group: "Apparence", icon: "palette", run: () => set({ theme: t.id }) });
    c.push({ id: "pz", label: "Personnaliser l'interface…", group: "Apparence", icon: "palette", run: onDrawer });
    c.push({ id: "act", label: `${p.activity ? "Masquer" : "Afficher"} le panneau d'activité`, group: "Apparence", icon: "panel", run: () => set({ activity: !p.activity }) });
    c.push({ id: "rail", label: `Rail : ${p.rail === "icones" ? "icônes + libellés" : "icônes seules"}`, group: "Apparence", icon: "panel", run: () => set({ rail: p.rail === "icones" ? "libelles" : "icones" }) });
    return c;
  }, [q, camps.data, revs.data, p.activity, p.rail]);
  const words = q.toLowerCase().split(/\s+/).filter(Boolean);
  const list = cmds.filter((c) => words.every((w) => (c.label + " " + c.group).toLowerCase().includes(w))).slice(0, 60);
  const pick = (c?: Cmd) => { if (c) { c.run(); onClose(); } };
  return (
    <div className="overlay" onMouseDown={onClose}>
      <div className="palette" role="dialog" aria-label="Palette de commandes" onMouseDown={(e) => e.stopPropagation()}>
        <input ref={inp} value={q} placeholder="Écran, campagne, révision (rev_…), thème…" aria-label="Rechercher"
          onChange={(e) => { setQ(e.target.value); setI(0); }}
          onKeyDown={(e) => {
            if (e.key === "ArrowDown") { e.preventDefault(); setI((x) => Math.min(list.length - 1, x + 1)); }
            if (e.key === "ArrowUp") { e.preventDefault(); setI((x) => Math.max(0, x - 1)); }
            if (e.key === "Enter") pick(list[i]);
          }} />
        <ul role="listbox">
          {list.map((c, k) => <li key={c.id} role="option" aria-selected={k === i} className={k === i ? "on" : ""} onMouseEnter={() => setI(k)} onClick={() => pick(c)}>
            <Icon n={c.icon} s={16} />{c.label}<span className="g">{c.group}</span></li>)}
          {!list.length && <li className="muted">Aucun résultat.</li>}
        </ul>
      </div>
    </div>
  );
}

function EngineDown({ detail }: { detail?: string }) {
  const [log, setLog] = useState("");
  useEffect(() => { window.qlab.engineLog().then(setLog); }, []);
  return (
    <div>
      <h1>Le moteur scientifique n'a pas démarré</h1>
      <div className="alert err">{detail}</div>
      <p>Vérifier l'installation (uv, Python 3.13) : voir <code>docs/operations/troubleshooting.md</code>.</p>
      <pre className="json">{log}</pre>
    </div>
  );
}

createRoot(document.getElementById("root")!).render(<PrefsProvider><App /></PrefsProvider>);
