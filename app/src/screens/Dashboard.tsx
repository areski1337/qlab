import React from "react";
import { Badge, Card, Err, fmt, PageHead, STATUS_FR, Table, Tile, useApi } from "../ui";
import { Explain } from "../charts";
import { useNav } from "../main";

export const LADDER = ["unverified", "screened", "historically_tested", "robustness_tested", "oos_evaluated", "reference_matched", "mt5_validated", "demo_observed"];

export function Dashboard() {
  const { go } = useNav();
  const h = useApi("/health", [], true);
  const st = useApi("/stats", [], true);
  const tasks = useApi<any[]>("/tasks", [], "progress");
  const camps = useApi<any[]>("/campaigns", [], "progress");
  const s = st.data;
  const by: Record<string, number> = s?.revisions_by_status ?? {};
  const total = Object.values(by).reduce((a, b) => a + (b as number), 0);
  const active = tasks.data?.filter((t) => ["queued", "validating", "running", "paused"].includes(t.state)) ?? null;
  const atLeast = (k: string) => LADDER.slice(LADDER.indexOf(k)).reduce((a, x) => a + (by[x] ?? 0), 0);
  return (
    <div>
      <PageHead title="Tableau de bord" sub="Vue d'ensemble : où en sont les stratégies, ce qui tourne, ce qui demande votre attention.">
        <button className="btn primary" onClick={() => go({ screen: "campaigns" })}>Nouvelle campagne</button>
      </PageHead>
      <Err msg={h.error || st.error} />
      {s?.alerts?.length > 0 && <Card title={`Alertes critiques · ${s.alerts.length}`} wide actions={<button className="btn" onClick={() => go({ screen: "tasks" })}>Voir les tâches</button>}>
        {s.alerts.slice(0, 4).map((a: string, i: number) => <details key={i} className="alert err" style={{ whiteSpace: "normal" }}>
          <summary style={{ cursor: "pointer" }}>{a.replace(/\s+/g, " ").slice(0, 170)}…</summary><pre style={{ margin: "6px 0 0", whiteSpace: "pre-wrap", font: "11px var(--font-num)" }}>{a}</pre></details>)}
        {s.alerts.length > 4 && <p className="muted">… et {s.alerts.length - 4} autre(s) : voir « Tâches & journaux ».</p>}
      </Card>}
      <div className="tiles">
        <Tile l="Stratégies" v={fmt(total, 0)} s={`${fmt(by.rejected ?? 0, 0)} rejetées`} />
        <Tile l="Robustesse ou plus" v={fmt(atLeast("robustness_tested"), 0)} s="ont survécu aux tests de stress" tone={atLeast("robustness_tested") ? "good" : null} />
        <Tile l="Validées MT5" v={fmt(atLeast("mt5_validated"), 0)} s="prêtes pour la démo" tone={atLeast("mt5_validated") ? "good" : null} />
        <Tile l="Tâches actives" v={fmt(active?.length ?? 0, 0)} s={active?.some((t) => t.state === "running") ? "en cours d'exécution" : "aucune en exécution"} />
        <Tile l="Évaluations" v={fmt(s?.evaluations ?? 0, 0)} s={`${fmt(s?.datasets ?? 0, 0)} datasets`} />
        <Tile l="Disque libre" v={h.data ? `${fmt(h.data.disk_free_mb / 1024, 0)} Go` : "—"} s={h.data ? `schéma v${h.data.schema}` : ""} tone={h.data && h.data.disk_free_mb < 10240 ? "bad" : null} />
      </div>
      <div className="grid">
        <Card title="Entonnoir de validation" span2>
          <Funnel by={by} />
          <Explain>Chaque barre = nombre de stratégies <b>ayant atteint au moins</b> cette étape. L'entonnoir se resserre : c'est normal, chaque étape exige des preuves (robustesse, hors échantillon, parité MT5). Longueur en <b>échelle logarithmique</b> (chaque graduation ×10) pour garder visibles les petits effectifs ; le nombre exact est à droite. Cliquer ouvre la comparaison.</Explain>
        </Card>
        <Card title="Système">
          {h.data && <dl className="kv">
            <dt>Moteur</dt><dd>{h.data.versions.engine} ({h.data.versions.channel})</dd>
            <dt>Base SQLite</dt><dd>{h.data.sqlite} · schéma v{h.data.schema}</dd>
            <dt>Worker</dt><dd>{h.data.worker_alive ? "actif" : "inactif"}</dd>
            <dt>Terminal MT5</dt><dd>{h.data.mt5.terminal_found ? "trouvé" : "introuvable"}</dd>
            <dt>MetaEditor</dt><dd>{h.data.mt5.metaeditor_found ? "trouvé" : "introuvable"}</dd>
            <dt>Données</dt><dd><code>{h.data.data_dir}</code></dd>
            <dt>Trading réel</dt><dd className="real-off">{h.data.live_trading}</dd>
          </dl>}
        </Card>
        <Card title="Tâches actives" actions={<button className="btn" onClick={() => go({ screen: "tasks" })}>Toutes</button>}>
          <Table rows={active} empty="Aucune tâche active." cols={[
            { k: "kind", t: "Type" }, { k: "state", t: "État", f: (r) => <Badge s={r.state} /> },
            { k: "progress", t: "Progression", f: (r) => <div className="progress"><i style={{ width: `${r.progress * 100}%` }} /></div> },
          ]} />
        </Card>
        <Card title="Campagnes récentes" span2>
          <Table rows={camps.data?.slice(0, 8) ?? null} onRow={(r) => go({ screen: "lab", campaign: r.id })} empty="Aucune campagne : lancez-en une." cols={[
            { k: "name", t: "Nom" }, { k: "task_state", t: "État", f: (r) => <Badge s={r.task_state} /> },
            { k: "progress", t: "Progression", f: (r) => <div style={{ display: "flex", gap: 8, alignItems: "center" }}><div className="progress" style={{ flex: 1 }}><i style={{ width: `${r.progress * 100}%` }} /></div>{fmt(r.progress * 100, 0)} %</div> },
            { k: "n_candidates", t: "Candidats", num: true }, { k: "created_at", t: "Créée (UTC)" },
          ]} />
        </Card>
      </div>
    </div>
  );
}

function Funnel({ by }: { by: Record<string, number> }) {
  const { go } = useNav();
  const cum = LADDER.map((k, i) => ({ k, n: LADDER.slice(i).reduce((a, x) => a + (by[x] ?? 0), 0) }));
  const max = Math.max(1, cum[0].n + (by.rejected ?? 0));
  const w = (n: number) => (n ? (Math.log10(n + 1) / Math.log10(max + 1)) * 100 : 0);  // log : 3 000 et 3 restent lisibles côte à côte
  return (
    <div style={{ display: "grid", gap: 6 }}>
      {[{ k: "all", n: max, label: "Toutes (y compris rejetées)" }, ...cum.map((c) => ({ ...c, label: STATUS_FR[c.k] }))].map((c, i) => (
        <div key={c.k} onClick={() => go({ screen: "pareto" })} style={{ display: "grid", gridTemplateColumns: "190px 1fr 60px", gap: 10, alignItems: "center", cursor: "pointer" }}>
          <span className={i === 0 ? "muted" : ""}>{c.label}</span>
          <div style={{ height: 16, background: "var(--grid)", borderRadius: 4, overflow: "hidden" }}>
            <div style={{ height: "100%", width: `${w(c.n)}%`, minWidth: c.n ? 3 : 0, borderRadius: 4,
              background: i === 0 ? "var(--mut)" : `linear-gradient(90deg, var(--acc), color-mix(in srgb, var(--acc2) ${(i / LADDER.length) * 100}%, var(--acc)))`, opacity: i === 0 ? 0.35 : 1 }} />
          </div>
          <span style={{ fontFamily: "var(--font-num)", textAlign: "right" }}>{fmt(c.n, 0)}</span>
        </div>))}
    </div>
  );
}
