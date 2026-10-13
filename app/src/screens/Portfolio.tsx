import React, { useState } from "react";
import { api } from "../api";
import { Badge, Btn, Card, Err, Field, fmt, Json, Table, useAction, useApi } from "../ui";

export function Portfolio() {
  const revs = useApi<any[]>("/genomes?limit=2000", [], true);
  const pfs = useApi<any[]>("/portfolios", [], true);
  const [sel, setSel] = useState<string[]>([]);
  const [f, setF] = useState({ name: "Portefeuille", method: "min_corr", segment: "research", w_min: 0.05, w_max: 0.5 });
  const [cur, setCur] = useState<any>(null);
  const a = useAction();
  const eligible = revs.data?.filter((r) => !["unverified", "rejected", "quarantined"].includes(r.status)) ?? null;
  const rep = cur?.report;
  return (
    <div>
      <h1>Portefeuilles & exposition</h1>
      <div className="grid">
        <Card title="Construire un portefeuille" wide>
          <p className="muted">Allocation bornée visant la complémentarité et la stabilité (pas la somme des profits). Utilise les transactions conservées d'un segment déjà évalué ; le holdout final est exclu.</p>
          <div className="row">
            <Field label="Nom"><input value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} /></Field>
            <Field label="Méthode"><select value={f.method} onChange={(e) => setF({ ...f, method: e.target.value })}>
              <option value="min_corr">complémentarité (1/σ × décorrélation)</option><option value="inverse_vol">inverse volatilité</option><option value="equal">poids égaux</option></select></Field>
            <Field label="Segment"><select value={f.segment} onChange={(e) => setF({ ...f, segment: e.target.value })}><option value="research">entraînement + validation</option><option value="oos">hors échantillon</option></select></Field>
            <Field label="Poids min"><input type="number" step="0.01" value={f.w_min} onChange={(e) => setF({ ...f, w_min: Number(e.target.value) })} /></Field>
            <Field label="Poids max"><input type="number" step="0.01" value={f.w_max} onChange={(e) => setF({ ...f, w_max: Number(e.target.value) })} /></Field>
          </div>
          <Table rows={eligible} empty="Aucune stratégie au statut ≥ filtrée." cols={[
            { k: "id", t: "", f: (r) => <input type="checkbox" checked={sel.includes(r.id)} onChange={(e) => setSel(e.target.checked ? [...sel, r.id] : sel.filter((x) => x !== r.id))} /> },
            { k: "id", t: "Révision" }, { k: "status", t: "Statut", f: (r) => <Badge s={r.status} /> }, { k: "campaign_id", t: "Campagne" }]} />
          <Btn kind="primary" busy={a.busy} disabled={sel.length < 2} onClick={() => a.run(async () => { const r = await api.post("/portfolios", { ...f, revision_ids: sel }); setCur(r); return r; }, (r) => `Portefeuille ${r.id} créé.`)}>Construire ({sel.length})</Btn>
          {a.view}
        </Card>
        <Card title="Portefeuilles enregistrés" wide>
          <Err msg={pfs.error} />
          <Table rows={pfs.data} onRow={async (p) => setCur(await api.get(`/portfolios/${p.id}`))} cols={[
            { k: "name", t: "Nom" }, { k: "method", t: "Méthode" }, { k: "version", t: "Version" },
            { k: "allocations", t: "Poids", f: (p) => p.allocations.map((x: any) => `${x.revision_id.slice(-6)}:${fmt(x.weight * 100, 1)}%`).join("  ") },
            { k: "created_at", t: "Créé (UTC)" }]} />
        </Card>
        {rep && <>
          <Card title="Portefeuille combiné (pondéré)">
            <dl className="kv">
              <dt>Rendement</dt><dd>{fmt(rep.portfolio.return_pct)} % sur {rep.portfolio.days} jours ({rep.segment})</dd>
              <dt>Drawdown max</dt><dd>{fmt(rep.portfolio.max_dd_pct)} %</dd>
              <dt>Sharpe (journalier, √252)</dt><dd>{fmt(rep.portfolio.sharpe)}</dd>
              <dt>Drawdowns simultanés</dt><dd>{fmt(rep.simultaneous_drawdown_ratio * 100, 1)} % des jours (≥ 2 stratégies sous -2 %)</dd>
              <dt>Concentration (HHI)</dt><dd>{fmt(rep.concentration_hhi, 3)}</dd>
            </dl>
            {rep.notes.map((n: string, i: number) => <p key={i} className="muted">{n}</p>)}
          </Card>
          <Card title="Poids, risque marginal et drawdown individuel">
            <Table rows={rep.strategies.map((s: string, i: number) => ({ id: s, w: rep.weights[i], mrc: rep.marginal_risk_contribution[s], dd: rep.individual_max_dd_pct[s] }))}
              cols={[{ k: "id", t: "Révision" }, { k: "w", t: "Poids", num: true, f: (r) => `${fmt(r.w * 100, 1)} %` },
                { k: "mrc", t: "Contrib. risque", num: true, f: (r) => r.mrc == null ? "—" : `${fmt(r.mrc * 100, 1)} %` }, { k: "dd", t: "DD max %", num: true }]} />
          </Card>
          <Card title="Corrélations des rendements journaliers" wide>
            <Table rows={rep.strategies.map((a: string) => ({ id: a, ...Object.fromEntries(rep.strategies.map((b: string) => [b, rep.correlation[a][b]])) }))}
              cols={[{ k: "id", t: "" }, ...rep.strategies.map((b: string) => ({ k: b, t: b.slice(-6), num: true }))]} />
          </Card>
          <Card title="Exposition"><Json v={{ instruments: rep.exposure_by_instrument, devises_nettes: rep.net_exposure_by_currency, chevauchement_signaux: rep.signal_overlap_jaccard, couts_agreges: rep.aggregate_costs }} /></Card>
        </>}
      </div>
    </div>
  );
}

export function Demo() {
  const d = useApi("/demo", [], true);
  const revs = useApi<any[]>("/genomes?status=mt5_validated", [], true);
  const [rid, setRid] = useState("");
  const a = useAction();
  const data = d.data as any;
  return (
    <div>
      <h1>Surveillance du compte démo</h1>
      <div className="alert warn">Environnement DÉMO. QLab n'envoie aucun ordre : l'EA est attaché au graphique et l'AutoTrading activé manuellement par vous dans MetaTrader 5. L'observation est en lecture seule et refuse les comptes réels. Suspendre bloque les nouvelles entrées sans fermer les positions ouvertes.</div>
      <Err msg={d.error} />
      <div className="grid">
        <Card title="Arrêt d'urgence (toutes les stratégies QLab)">
          <p>État : {data?.emergency_stop == null ? "inconnu (dossier MT5 introuvable)" : data.emergency_stop ? <strong className="real-off">ACTIF — aucune nouvelle entrée</strong> : "inactif"}</p>
          <div className="actions">
            <Btn kind="danger" busy={a.busy} onClick={() => a.run(() => api.post("/demo/emergency-stop", { on: true, reason: "arrêt d'urgence manuel" }), () => "Arrêt d'urgence activé.")}>Activer</Btn>
            <Btn busy={a.busy} onClick={() => a.run(() => api.post("/demo/emergency-stop", { on: false, reason: "levée manuelle" }), () => "Arrêt d'urgence levé.")}>Lever</Btn>
          </div>
          <p className="muted">Filtre d'annonces : {data?.news_filter}. Clôture avant week-end : {data?.weekend_close}.</p>
          {a.view}
        </Card>
        <Card title="Enregistrer un déploiement démo">
          <p className="muted">Réservé aux stratégies « validée MT5 ». Démarre au palier de risque 25 % (InpRiskScale = 0,25), puis 50 % et 100 % après 20 trades sans alerte.</p>
          <Field label="Révision validée MT5"><select value={rid} onChange={(e) => setRid(e.target.value)}>
            <option value="">— choisir —</option>{revs.data?.map((r) => <option key={r.id} value={r.id}>{r.id}</option>)}</select></Field>
          <Btn kind="primary" busy={a.busy} disabled={!rid} onClick={() => a.run(() => api.post("/demo/register", { revision_id: rid }), (r) => `Déploiement ${r.id} enregistré (magic ${r.magic}).`)}>Enregistrer</Btn>
        </Card>
        <Card title="Déploiements" wide>
          <Table rows={data?.deployments ?? null} empty="Aucun déploiement démo." cols={[
            { k: "id", t: "ID" }, { k: "revision_id", t: "Révision" }, { k: "magic", t: "Magic" }, { k: "state", t: "État" },
            { k: "risk_stage", t: "Palier", f: (r) => `${fmt(r.risk_stage * 100, 0)} %` }, { k: "server", t: "Serveur" },
            { k: "last_observation", t: "Dernière observation", f: (r) => r.last_observation ? `${r.last_observation.n_live} trades · ${r.last_observation.alerts.length} alerte(s)` : "—" },
            { k: "id", t: "Actions", f: (r) => <span className="actions">
              <button className="btn" onClick={() => a.run(() => api.post(`/demo/${r.id}/observe`), (x) => `Observation soumise (tâche ${x.task_id}).`)}>Observer</button>
              <button className="btn" onClick={() => a.run(() => api.post(`/demo/${r.id}/promote`), (x) => x.instruction)}>Palier suivant</button>
              <button className="btn danger" onClick={() => a.run(() => api.post(`/demo/${r.id}/suspend`, { on: true, reason: "suspension manuelle" }), () => "Suspendue.")}>Suspendre</button>
            </span> }]} />
        </Card>
        {data?.deployments?.filter((x: any) => x.last_observation).map((x: any) => (
          <Card key={x.id} title={`Observation ${x.id}`}>
            {x.last_observation.alerts.map((al: string, i: number) => <div key={i} className="alert err">{al}</div>)}
            <Json v={x.last_observation.checks} />
          </Card>))}
      </div>
    </div>
  );
}
