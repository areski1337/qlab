import React, { useEffect, useState } from "react";
import { api } from "../api";
import { Badge, Btn, Card, Err, Field, fmt, Json, Table, useAction, useApi, utc } from "../ui";

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

function CalendarCard() {
  const c = useApi("/calendar", [], true);
  const a = useAction();
  const [r, setR] = useState({ from: "2020-01-01", to: new Date(Date.now() + 14 * 864e5).toISOString().slice(0, 10) });
  const d = c.data as any;
  return (
    <Card title="Calendrier économique (API officielle FXStreet)">
      <p className="muted">Clés fournies par FXStreet (OAuth2), lues uniquement depuis les variables d'environnement QLAB_FXSTREET_CLIENT_ID / QLAB_FXSTREET_CLIENT_SECRET ; jamais stockées. Données à usage personnel, non incluses dans les exports.</p>
      <Err msg={c.error} />
      {d && <dl className="kv">
        <dt>Clés configurées</dt><dd className={d.credentials_configured ? "" : "real-off"}>{d.credentials_configured ? "oui" : "non — filtre inactif tant qu'aucune donnée n'est récupérée"}</dd>
        <dt>Événements</dt><dd>{fmt(d.events, 0)}</dd>
        <dt>Couverture</dt><dd>{d.coverage_from ? `${utc(d.coverage_from)} → ${utc(d.coverage_to)}` : "aucune"}</dd>
        <dt>Dernier rafraîchissement</dt><dd>{d.last_refresh ?? "—"}</dd>
      </dl>}
      <div className="row">
        <Field label="Du"><input type="date" value={r.from} onChange={(e) => setR({ ...r, from: e.target.value })} /></Field>
        <Field label="Au"><input type="date" value={r.to} onChange={(e) => setR({ ...r, to: e.target.value })} /></Field>
      </div>
      <Btn busy={a.busy} disabled={!d?.credentials_configured} onClick={() => a.run(() => api.post("/calendar/refresh", r), (x) => `Récupération soumise (tâche ${x.task_id}).`)}>Récupérer</Btn>
      {a.view}
      {d?.upcoming_high?.length > 0 && <Table rows={d.upcoming_high.slice(0, 20).map((x: any, i: number) => ({ id: i, ...x }))} cols={[
        { k: "date_ts", t: "Date", f: (x) => utc(x.date_ts) }, { k: "currency", t: "Devise" }, { k: "name", t: "Événement" }, { k: "volatility", t: "Impact" }]} />}
    </Card>
  );
}

function EngineExperiments() {
  const ex = useApi("/engine-experiments", [], true);
  const ds = useApi<any[]>("/datasets");
  const a = useAction();
  const [f, setF] = useState({ hypothesis: "", dsv: "", key: "crossover_rate", base: "0.3", variant: "0.5", metric: "best_validation_sharpe", spread: "" });
  const d = ex.data as any;
  const parse = (v: string) => (isNaN(Number(v)) ? v : Number(v));
  return (
    <Card title="Expériences sur les méthodes de recherche (évolution du moteur)" wide>
      <p className="muted">Compare une méthode de base et une variante sur ≥ 3 graines, hypothèse et critères fixés avant exécution (gain sur ≥ 70 % des graines et test des signes p ≤ 0,1). Seuls des paramètres de méthode peuvent varier : contraintes, coûts, protocole et limites de risque sont exclus. Une variante gagnante n'est jamais appliquée automatiquement ; elle peut être promue dans le canal « expérimental » (retour arrière possible).</p>
      <div className="row">
        <Field label="Hypothèse"><input style={{ width: 360 }} value={f.hypothesis} onChange={(e) => setF({ ...f, hypothesis: e.target.value })} /></Field>
        <Field label="Dataset"><select value={f.dsv} onChange={(e) => setF({ ...f, dsv: e.target.value })}><option value="">—</option>{ds.data?.map((x) => <option key={x.id} value={x.id}>{x.canonical_symbol} {x.timeframe} v{x.version}</option>)}</select></Field>
        <Field label="Paramètre"><select value={f.key} onChange={(e) => setF({ ...f, key: e.target.value })}>{d?.method_keys?.map((k: string) => <option key={k}>{k}</option>)}</select></Field>
        <Field label="Base"><input value={f.base} onChange={(e) => setF({ ...f, base: e.target.value })} /></Field>
        <Field label="Variante"><input value={f.variant} onChange={(e) => setF({ ...f, variant: e.target.value })} /></Field>
        <Field label="Métrique"><select value={f.metric} onChange={(e) => setF({ ...f, metric: e.target.value })}>{d?.metrics?.map((k: string) => <option key={k}>{k}</option>)}</select></Field>
        <Field label="Spread plancher (pts)"><input value={f.spread} onChange={(e) => setF({ ...f, spread: e.target.value })} /></Field>
      </div>
      <Btn kind="primary" busy={a.busy} disabled={!f.dsv || f.hypothesis.length < 10} onClick={() => a.run(() => api.post("/engine-experiments", {
        hypothesis: f.hypothesis, spec: {
          base: { dataset_version_id: f.dsv, population: 12, generations_per_tribe: 4, merge_generations: 2, tribes: ["growth", "consistency"], workers: 4,
            cost_profile: { name: "exp", version: 1, spread_mode: "max", fixed_spread_points: f.spread === "" ? null : Number(f.spread), commission_per_lot_side: 0, slippage_points: 0, apply_swap: true, provenance: {} } },
          baseline: { [f.key]: parse(f.base) }, variant: { [f.key]: parse(f.variant) }, seeds: [1, 2, 3, 4, 5], metric: f.metric, direction: "higher" },
      }), (r) => `Expérience soumise (tâche ${r.task_id}).`)}>Lancer l'expérience</Btn>
      <Btn busy={a.busy} onClick={() => a.run(() => api.post("/engine-rollback"), () => "Retour arrière du canal expérimental effectué.")}>Retour arrière</Btn>
      {a.view}
      <p>Canal expérimental actuel : <code>{JSON.stringify(d?.experimental_overrides ?? {})}</code></p>
      <Table rows={d?.experiments ?? null} empty="Aucune expérience." cols={[
        { k: "created_at", t: "Date (UTC)" }, { k: "hypothesis", t: "Hypothèse" }, { k: "verdict", t: "Verdict", f: (r) => r.verdict ?? "en cours" },
        { k: "results.win_ratio", t: "Gains", f: (r) => r.results ? `${r.results.wins}/${r.results.rows.length}` : "—" },
        { k: "results.sign_test_p", t: "p", num: true },
        { k: "id", t: "", f: (r) => r.verdict === "promote_candidate" ? <button className="btn" onClick={() => a.run(() => api.post(`/engine-experiments/${r.id}/promote`), () => "Promue dans le canal expérimental.")}>Promouvoir (expérimental)</button> : null }]} />
    </Card>
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
            <div className="row">
              <Field label="Objectif de gain journalier (%, vide = aucun)"><input type="number" step="0.1" value={lim.daily_profit_target_pct ?? ""} onChange={num("daily_profit_target_pct")} /></Field>
              <Field label="Clôture avant week-end (min, vide = non)"><input type="number" value={lim.close_before_weekend_minutes ?? ""} onChange={num("close_before_weekend_minutes")} /></Field>
            </div>
            <div className="row">
              <label><input type="checkbox" checked={!!lim.news_filter?.enabled} onChange={(e) => setLim({ ...lim, news_filter: { ...lim.news_filter, enabled: e.target.checked } })} /> Filtre d'annonces (FXStreet)</label>
              <Field label="Avant (min)"><input type="number" value={lim.news_filter?.before_min ?? 30} onChange={(e) => setLim({ ...lim, news_filter: { ...lim.news_filter, before_min: Number(e.target.value) } })} /></Field>
              <Field label="Après (min)"><input type="number" value={lim.news_filter?.after_min ?? 30} onChange={(e) => setLim({ ...lim, news_filter: { ...lim.news_filter, after_min: Number(e.target.value) } })} /></Field>
              <Field label="Impact minimal"><select value={lim.news_filter?.min_volatility ?? "HIGH"} onChange={(e) => setLim({ ...lim, news_filter: { ...lim.news_filter, min_volatility: e.target.value } })}><option>HIGH</option><option>MEDIUM</option><option>LOW</option></select></Field>
            </div>
            <p className="muted">Filtre actif sans calendrier couvrant la période : toute entrée est refusée (prudence).</p>
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
        <CalendarCard />
        <EngineExperiments />
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
