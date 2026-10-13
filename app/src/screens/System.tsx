import React, { useEffect, useState } from "react";
import { api } from "../api";
import { Badge, Btn, Card, Err, Field, fmt, Json, Table, useAction, useApi } from "../ui";

export function Tasks() {
  const t = useApi<any[]>("/tasks", [], true);
  const logs = useApi<any[]>("/logs?n=300", [], true);
  const audit = useApi<any[]>("/audit?n=300", [], true);
  const [sel, setSel] = useState<any>(null);
  const detail = useApi(sel ? `/tasks/${sel.id}` : null, [sel?.id], true);
  const a = useAction();
  const act = (id: string, x: string) => a.run(() => api.post(`/tasks/${id}/${x}`), () => `Action « ${x} » appliquée`);
  return (
    <div>
      <h1>Tâches, journaux & diagnostics</h1>
      {a.view}
      <div className="grid">
        <Card title="Tâches" wide>
          <Err msg={t.error} />
          <Table rows={t.data} onRow={setSel} cols={[
            { k: "created_at", t: "Créée (UTC)" }, { k: "kind", t: "Type" }, { k: "state", t: "État", f: (r) => <Badge s={r.state} /> },
            { k: "progress", t: "Progr.", f: (r) => `${fmt(r.progress * 100, 0)} %` }, { k: "attempts", t: "Essais", num: true },
            { k: "error", t: "Erreur", f: (r) => (r.error ?? "").slice(0, 80) },
            { k: "id", t: "Actions", f: (r) => <span className="actions" onClick={(e) => e.stopPropagation()}>
              {["queued", "running"].includes(r.state) && r.kind === "campaign" && <button className="btn" onClick={() => act(r.id, "pause")}>Pause</button>}
              {r.state === "paused" && <button className="btn" onClick={() => act(r.id, "resume")}>Reprendre</button>}
              {r.state === "failed" && <button className="btn" onClick={() => act(r.id, "retry")}>Relancer</button>}
              {["queued", "paused"].includes(r.state) && <button className="btn danger" onClick={() => act(r.id, "cancel")}>Annuler</button>}
            </span> }]} />
        </Card>
        {detail.data && <Card title={`Tâche ${sel.id}`} wide><Json v={detail.data} /></Card>}
        <Card title="Journal structuré (UTC)" wide>
          <Table rows={logs.data ? [...logs.data].reverse() : null} cols={[{ k: "ts", t: "Horodatage" }, { k: "level", t: "Niveau" }, { k: "event", t: "Événement" },
            { k: "correlation_id", t: "Corrélation" }, { k: "error", t: "Détail", f: (r) => (r.error ?? r.migrations ?? "").toString().slice(0, 120) }]} />
        </Card>
        <Card title="Audit" wide>
          <Table rows={audit.data} cols={[{ k: "ts", t: "Horodatage" }, { k: "kind", t: "Événement" }, { k: "subject_id", t: "Sujet" },
            { k: "payload_json", t: "Contenu", f: (r) => r.payload_json.slice(0, 140) }]} />
        </Card>
      </div>
    </div>
  );
}

export function Settings() {
  const s = useApi("/settings", [], true);
  const h = useApi("/health", [], true);
  const b = useApi<any[]>("/backups", [], true);
  const [lim, setLim] = useState<any>(null);
  const [vr, setVr] = useState<any>(null);
  useEffect(() => { if (s.data) setLim((s.data as any).risk_limits); }, [s.data]);
  const save = useAction(), bk = useAction(), ver = useAction();
  const num = (k: string) => (e: any) => setLim({ ...lim, [k]: e.target.value === "" ? null : Number(e.target.value) });
  return (
    <div>
      <h1>Paramètres, ressources & sauvegardes</h1>
      <div className="grid">
        <Card title="Limites absolues de risque (contrôleur indépendant)">
          <p className="muted">Ces limites s'imposent à toutes les stratégies et ne font pas partie de l'espace de recherche. Valeurs initiales configurables, pas des recommandations. Plafonds logiciels : risque/trade ≤ 5 %, perte journalière ≤ 20 %, drawdown ≤ 60 %.</p>
          {lim && <>
            <div className="row">
              <Field label="Risque max / trade (%)"><input type="number" step="0.1" value={lim.max_risk_per_trade_pct} onChange={num("max_risk_per_trade_pct")} /></Field>
              <Field label="Perte journalière max (%)"><input type="number" step="0.1" value={lim.max_daily_loss_pct} onChange={num("max_daily_loss_pct")} /></Field>
              <Field label="Drawdown max (%)"><input type="number" step="0.5" value={lim.max_drawdown_pct} onChange={num("max_drawdown_pct")} /></Field>
            </div>
            <div className="row">
              <Field label="Positions max"><input type="number" value={lim.max_open_positions} onChange={num("max_open_positions")} /></Field>
              <Field label="Lots max"><input type="number" step="0.01" value={lim.max_lots} onChange={num("max_lots")} /></Field>
              <Field label="Ordres max / jour"><input type="number" value={lim.max_orders_per_day} onChange={num("max_orders_per_day")} /></Field>
              <Field label="Spread max (points, vide = aucun)"><input type="number" value={lim.max_spread_points ?? ""} onChange={num("max_spread_points")} /></Field>
            </div>
            <p className="real-off">Trading réel : désactivé — non activable dans cette version.</p>
            <Btn kind="primary" busy={save.busy} onClick={() => save.run(() => api.put("/risk-limits", { ...lim, live_trading_enabled: false }), () => "Limites enregistrées (audit).")}>Enregistrer</Btn>
            {save.view}
          </>}
        </Card>
        <Card title="Ressources">
          {h.data && <dl className="kv">
            <dt>Répertoire de données</dt><dd><code>{(h.data as any).data_dir}</code></dd>
            <dt>Disque libre</dt><dd>{fmt((h.data as any).disk_free_mb / 1024, 1)} Go</dd>
            <dt>Données MT5</dt><dd><code>{(h.data as any).mt5.data_path || "non détecté"}</code></dd>
            <dt>Workers (défaut)</dt><dd>{(s.data as any)?.settings.workers.max_processes}</dd>
          </dl>}
          <h3>Configuration</h3><Json v={(s.data as any)?.settings} />
        </Card>
        <Card title="Sauvegardes" wide actions={<Btn busy={bk.busy} kind="primary" onClick={() => bk.run(() => api.post("/backups"), (r) => `Sauvegarde soumise (tâche ${r.task_id}).`)}>Sauvegarder maintenant</Btn>}>
          {bk.view}
          <p className="muted">Archive cohérente : base SQLite (API backup), artefacts et datasets, manifeste d'empreintes. « Vérifier » restaure dans un répertoire temporaire et contrôle empreintes et références sans toucher aux données. Restauration complète : voir docs/operations/backup-restore.md.</p>
          <Table rows={b.data?.map((x) => ({ id: x.name, ...x })) ?? null} cols={[{ k: "name", t: "Fichier" }, { k: "size", t: "Taille (Mo)", num: true, f: (r) => fmt(r.size / 2 ** 20, 1) },
            { k: "id", t: "", f: (r) => r.name.endsWith(".zip") ? <button className="btn" onClick={() => ver.run(async () => { const x = await api.post("/backups/verify", { name: r.name }); setVr(x); return x; }, (x) => x.ok ? "Sauvegarde intègre." : "Sauvegarde INVALIDE.")}>Vérifier</button> : <span className="muted">pré-migration</span> }]} />
          {ver.view}
          {vr && <Json v={vr} />}
        </Card>
      </div>
    </div>
  );
}
