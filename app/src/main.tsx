import React, { createContext, useContext, useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import "./styles.css";
import { Dashboard } from "./screens/Dashboard";
import { Campaigns, CampaignLab, Pareto } from "./screens/Campaigns";
import { Data } from "./screens/Data";
import { GenomeExplorer, Passport, Backtests } from "./screens/Genome";
import { Mt5 } from "./screens/Mt5";
import { Portfolio, Demo } from "./screens/Portfolio";
import { Tasks, Settings } from "./screens/System";

export type Nav = { screen: string; rev?: string; campaign?: string };
export const NavCtx = createContext<{ nav: Nav; go: (n: Nav) => void }>({ nav: { screen: "dash" }, go: () => {} });
export const useNav = () => useContext(NavCtx);

const SCREENS: [string, string, React.FC][] = [
  ["dash", "Tableau de bord", Dashboard],
  ["campaigns", "Campagnes", Campaigns],
  ["data", "Données & qualité", Data],
  ["lab", "Laboratoire génétique", CampaignLab],
  ["pareto", "Comparaison & Pareto", Pareto],
  ["genome", "Génome & généalogie", GenomeExplorer],
  ["passport", "Passeport", Passport],
  ["backtests", "Backtests & transactions", Backtests],
  ["mt5", "MQL5 & validation MT5", Mt5],
  ["portfolio", "Portefeuilles", Portfolio],
  ["demo", "Surveillance démo", Demo],
  ["tasks", "Tâches & journaux", Tasks],
  ["settings", "Paramètres & sauvegardes", Settings],
];

function App() {
  const [nav, setNav] = useState<Nav>({ screen: "dash" });
  const [upd, setUpd] = useState<string | null>(null);
  const [engine, setEngine] = useState<{ state: string; detail?: string }>({ state: "démarrage du moteur…" });
  useEffect(() => window.qlab.onEvent((ev) => {
    if (ev.type === "engine.ready") setEngine({ state: "moteur prêt" });
    if (ev.type === "engine.failed") setEngine({ state: "moteur en échec", detail: ev.error });
    if (ev.type === "update.available") setUpd(ev.version);
    if (ev.type === "engine.exited") setEngine({ state: "moteur arrêté", detail: `code ${ev.code}` });
  }), []);
  useEffect(() => { window.qlab.request("GET", "/api/v1/health").then((r) => r.status === 200 && setEngine({ state: "moteur prêt" })); }, []);
  const Cur = SCREENS.find((s) => s[0] === nav.screen)?.[2] ?? Dashboard;
  return (
    <NavCtx.Provider value={{ nav, go: setNav }}>
      <div className="app">
        <div className="envbar" role="status">
          <span className="env">RECHERCHE / SIMULATION</span>
          <span className="real-off">Trading réel : désactivé</span>
          <span className="grow" />
          {upd && <button className="btn" onClick={() => setNav({ screen: "settings" })}>Mise à jour {upd} disponible</button>}
          <span className={engine.state === "moteur prêt" ? "muted" : "real-off"}>{engine.state}</span>
          {engine.detail && <span className="muted" title={engine.detail}>ⓘ</span>}
        </div>
        <nav aria-label="Écrans">
          {SCREENS.map(([k, label], i) => (
            <button key={k} className={nav.screen === k ? "on" : ""} onClick={() => setNav({ ...nav, screen: k })}>
              <span className="num">{i + 1}</span>{label}
            </button>))}
        </nav>
        <main>{engine.state === "moteur en échec" ? <EngineDown detail={engine.detail} /> : <Cur />}</main>
      </div>
    </NavCtx.Provider>
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

createRoot(document.getElementById("root")!).render(<App />);
