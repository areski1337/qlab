import React from "react";
import { Badge, Card, Err, fmt, Table, useApi } from "../ui";
import { useNav } from "../main";

export function Dashboard() {
  const { go } = useNav();
  const h = useApi("/health", [], true);
  const st = useApi("/stats", [], true);
  const tasks = useApi<any[]>("/tasks", [], true);
  const camps = useApi<any[]>("/campaigns", [], true);
  const s = st.data;
  return (
    <div>
      <h1>Tableau de bord</h1>
      <Err msg={h.error || st.error} />
      {s?.alerts?.length > 0 && (
        <Card title="Alertes critiques" wide>
          {s.alerts.map((a: string, i: number) => <div key={i} className="alert err">{a}</div>)}
        </Card>)}
      <div className="grid">
        <Card title="Système">
          {h.data && <dl className="kv">
            <dt>Moteur</dt><dd>{h.data.versions.engine} ({h.data.versions.channel})</dd>
            <dt>Base SQLite</dt><dd>{h.data.sqlite} · schéma v{h.data.schema}</dd>
            <dt>Disque libre</dt><dd>{fmt(h.data.disk_free_mb / 1024, 1)} Go</dd>
            <dt>Worker</dt><dd>{h.data.worker_alive ? "actif" : "inactif"}</dd>
            <dt>Terminal MT5</dt><dd>{h.data.mt5.terminal_found ? "trouvé" : "introuvable"}</dd>
            <dt>MetaEditor</dt><dd>{h.data.mt5.metaeditor_found ? "trouvé" : "introuvable"}</dd>
            <dt>Données</dt><dd><code>{h.data.data_dir}</code></dd>
            <dt>Trading réel</dt><dd className="real-off">{h.data.live_trading}</dd>
          </dl>}
        </Card>
        <Card title="Stratégies par statut">
          {s && <dl className="kv">{Object.entries(s.revisions_by_status).map(([k, v]) => (
            <React.Fragment key={k}><dt><Badge s={k} /></dt><dd>{fmt(v as number, 0)}</dd></React.Fragment>))}
            <dt>Évaluations</dt><dd>{fmt(s.evaluations, 0)}</dd>
            <dt>Datasets</dt><dd>{fmt(s.datasets, 0)}</dd>
          </dl>}
        </Card>
        <Card title="Tâches actives" actions={<button className="btn" onClick={() => go({ screen: "tasks" })}>Toutes</button>}>
          <Table rows={tasks.data?.filter((t) => ["queued", "validating", "running", "paused"].includes(t.state)) ?? null}
            empty="Aucune tâche active." cols={[
              { k: "kind", t: "Type" }, { k: "state", t: "État", f: (r) => <Badge s={r.state} /> },
              { k: "progress", t: "Progression", f: (r) => <div className="progress"><i style={{ width: `${r.progress * 100}%` }} /></div> },
            ]} />
        </Card>
        <Card title="Campagnes récentes" wide actions={<button className="btn primary" onClick={() => go({ screen: "campaigns" })}>Nouvelle campagne</button>}>
          <Table rows={camps.data?.slice(0, 8) ?? null} onRow={(r) => go({ screen: "lab", campaign: r.id })} cols={[
            { k: "name", t: "Nom" }, { k: "task_state", t: "État", f: (r) => <Badge s={r.task_state} /> },
            { k: "progress", t: "Progression", f: (r) => `${fmt(r.progress * 100, 0)} %` },
            { k: "n_candidates", t: "Candidats", num: true }, { k: "created_at", t: "Créée (UTC)" },
          ]} />
        </Card>
      </div>
    </div>
  );
}
