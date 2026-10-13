import React, { useState } from "react";
import { api } from "../api";
import { Badge, Btn, Card, Err, Field, fmt, Json, PageHead, Table, Tile, useAction, useApi, signTone } from "../ui";
import { Bars, Explain, Heatmap, Stack } from "../charts";

export function Portfolio() {
  const revs = useApi<any[]>("/genomes?limit=2000", [], true);
  const pfs = useApi<any[]>("/portfolios", [], true);
  const camps = useApi<any[]>("/campaigns");
  const [sel, setSel] = useState<string[]>([]);
  const [cid, setCid] = useState("");
  const [f, setF] = useState({ name: "Portefeuille", method: "min_corr", segment: "research", w_min: 0.05, w_max: 0.5 });
  const [cur, setCur] = useState<any>(null);
  const a = useAction();
  const eligible = revs.data?.filter((r) => !["unverified", "rejected", "quarantined"].includes(r.status)) ?? null;
  const rep = cur?.report;
  const short = (s: string) => s.slice(-6);
  return (
    <div>
      <PageHead title="Portefeuilles & exposition" sub="Allocation bornée visant la complémentarité et la stabilité, pas la somme des profits." />
      {rep && <div className="tiles">
        <Tile l="Rendement" v={`${fmt(rep.portfolio.return_pct, 1)} %`} tone={signTone(rep.portfolio.return_pct)} s={`${rep.portfolio.days} jours · ${rep.segment}`} />
        <Tile l="Drawdown max" v={`${fmt(rep.portfolio.max_dd_pct, 1)} %`} s="portefeuille combiné" />
        <Tile l="Sharpe" v={fmt(rep.portfolio.sharpe, 2)} tone={signTone(rep.portfolio.sharpe)} s="journalier annualisé (√252)" />
        <Tile l="Drawdowns simultanés" v={`${fmt(rep.simultaneous_drawdown_ratio * 100, 1)} %`} s="jours où ≥ 2 stratégies < −2 %" tone={rep.simultaneous_drawdown_ratio > 0.2 ? "bad" : null} />
        <Tile l="Concentration" v={fmt(rep.concentration_hhi, 3)} s={`HHI · 1/n = ${fmt(1 / rep.strategies.length, 3)}`} />
      </div>}
      <div className="grid">
        {rep && <>
          <Card title={`${cur.name ?? "Portefeuille"} — répartition`} wide>
            <Stack parts={rep.strategies.map((s: string, i: number) => ({ label: short(s), value: rep.weights[i] * 100 }))} />
            <Explain>Part du capital allouée à chaque stratégie. Méthode « complémentarité » : plus de poids aux stratégies <b>peu volatiles et peu corrélées</b> aux autres, dans les bornes min/max choisies.</Explain>
          </Card>
          <Card title="Contribution au risque">
            <Bars unit="% du risque" items={rep.strategies.map((s: string) => ({ label: short(s), value: rep.marginal_risk_contribution[s] == null ? null : rep.marginal_risk_contribution[s] * 100, tip: `DD individuel ${fmt(rep.individual_max_dd_pct[s], 1)} %` }))} />
            <Explain>Part du risque total (volatilité) apportée par chaque stratégie. Un portefeuille équilibré évite qu'une seule barre domine, même si son poids paraît modeste.</Explain>
          </Card>
          <Card title="Corrélations des rendements journaliers">
            <Heatmap rows={rep.strategies.map(short)} cols={rep.strategies.map(short)} get={(i, j) => rep.correlation[rep.strategies[i]][rep.strategies[j]]} unit="corrélation" max={1} pos="var(--down)" neg="var(--acc2)" />
            <Explain>Couleur chaude = évoluent ensemble (risque de pertes simultanées) ; violet = en sens opposé ; pâle = indépendantes. Hors diagonale, on cherche des cases <b>pâles ou violettes</b> : les pertes de l'une ne coïncident pas avec celles des autres.</Explain>
          </Card>
          <Card title="Exposition">
            <Json v={{ instruments: rep.exposure_by_instrument, devises_nettes: rep.net_exposure_by_currency, chevauchement_signaux: rep.signal_overlap_jaccard, couts_agreges: rep.aggregate_costs }} />
            {rep.notes.map((n: string, i: number) => <p key={i} className="muted">{n}</p>)}
          </Card>
        </>}
        <Card title="Construire un portefeuille" wide>
          <p className="muted">Utilise les transactions conservées d'un segment déjà évalué ; le holdout final est exclu.</p>
          <div className="row">
            <Field label="Nom"><input value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} /></Field>
            <Field label="Méthode"><select value={f.method} onChange={(e) => setF({ ...f, method: e.target.value })}>
              <option value="min_corr">complémentarité (1/σ × décorrélation)</option><option value="inverse_vol">inverse volatilité</option><option value="equal">poids égaux</option></select></Field>
            <Field label="Segment"><select value={f.segment} onChange={(e) => setF({ ...f, segment: e.target.value })}><option value="research">entraînement + validation</option><option value="oos">hors échantillon</option></select></Field>
            <Field label="Poids min"><input type="number" step="0.01" value={f.w_min} onChange={(e) => setF({ ...f, w_min: Number(e.target.value) })} /></Field>
            <Field label="Poids max"><input type="number" step="0.01" value={f.w_max} onChange={(e) => setF({ ...f, w_max: Number(e.target.value) })} /></Field>
          </div>
          <Table rows={eligible} empty="Aucune stratégie au statut ≥ filtrée." cols={[
            { k: "sel", t: "", f: (r) => <input type="checkbox" aria-label={`Sélectionner ${r.id}`} checked={sel.includes(r.id)} onChange={(e) => setSel(e.target.checked ? [...sel, r.id] : sel.filter((x) => x !== r.id))} /> },
            { k: "id", t: "Révision" }, { k: "status", t: "Statut", f: (r) => <Badge s={r.status} /> }, { k: "campaign_id", t: "Campagne" }]} />
          <div className="row" style={{ marginTop: 10, alignItems: "flex-end" }}>
            <Btn kind="primary" busy={a.busy} disabled={sel.length < 2} onClick={() => a.run(async () => { const r = await api.post("/portfolios", { ...f, revision_ids: sel }); setCur(r); return r; }, (r) => `Portefeuille ${r.id} créé.`)}>Construire ({sel.length})</Btn>
            <span className="muted" style={{ paddingBottom: 6 }}>ou</span>
            <Field label="Depuis une campagne"><select value={cid} onChange={(e) => setCid(e.target.value)}>
              <option value="">— campagne —</option>{camps.data?.map((c) => <option key={c.id} value={c.id}>{c.name} · {c.id}</option>)}</select></Field>
            <Btn busy={a.busy} disabled={!cid} onClick={() => a.run(async () => {
              const r = await api.post("/portfolios/from-campaign", { campaign_id: cid, method: f.method, w_min: f.w_min, w_max: f.w_max });
              setCur(r); return r;
            }, (r) => `Portefeuille ${r.id} créé depuis la campagne.`)}>Construire depuis la campagne</Btn>
          </div>
          {a.view}
        </Card>
        <Card title="Portefeuilles enregistrés" wide>
          <Err msg={pfs.error} />
          <Table rows={pfs.data} onRow={async (p) => setCur(await api.get(`/portfolios/${p.id}`))} cols={[
            { k: "name", t: "Nom", f: (p) => <b>{p.name}</b> }, { k: "method", t: "Méthode" }, { k: "version", t: "Version" },
            { k: "allocations", t: "Poids", f: (p) => p.allocations.map((x: any) => `${x.revision_id.slice(-6)}:${fmt(x.weight * 100, 1)}%`).join("  ") },
            { k: "created_at", t: "Créé (UTC)" }]} />
        </Card>
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
  const deps: any[] = data?.deployments ?? [];
  return (
    <div>
      <PageHead title="Surveillance démo" sub="Observation en lecture seule du compte démo MT5. QLab n'envoie aucun ordre." />
      <div className="alert warn">Environnement DÉMO. L'EA est attaché au graphique et l'AutoTrading activé manuellement par vous dans MetaTrader 5. L'observation refuse les comptes réels. Suspendre bloque les nouvelles entrées sans fermer les positions ouvertes.</div>
      <Err msg={d.error} />
      <div className="tiles">
        <Tile l="Arrêt d'urgence" v={data?.emergency_stop == null ? "inconnu" : data.emergency_stop ? "ACTIF" : "inactif"} tone={data?.emergency_stop ? "bad" : null} s={data?.emergency_stop == null ? "dossier MT5 introuvable" : "toutes stratégies QLab"} />
        <Tile l="Déploiements" v={fmt(deps.length, 0)} s={`${deps.filter((x) => x.state === "observing").length} en observation`} />
        <Tile l="Alertes" v={fmt(deps.reduce((n, x) => n + (x.last_observation?.alerts.length ?? 0), 0), 0)} tone={deps.some((x) => x.last_observation?.alerts.length) ? "bad" : null} s="dernières observations" />
        <Tile l="Filtre d'annonces" v={data?.news_filter ?? "—"} s={`week-end : ${data?.weekend_close ?? "—"}`} />
      </div>
      <div className="grid">
        <Card title="Arrêt d'urgence (toutes les stratégies QLab)">
          <div className="actions">
            <Btn kind="danger" busy={a.busy} onClick={() => a.run(() => api.post("/demo/emergency-stop", { on: true, reason: "arrêt d'urgence manuel" }), () => "Arrêt d'urgence activé.")}>Activer</Btn>
            <Btn busy={a.busy} onClick={() => a.run(() => api.post("/demo/emergency-stop", { on: false, reason: "levée manuelle" }), () => "Arrêt d'urgence levé.")}>Lever</Btn>
          </div>
          {a.view}
        </Card>
        <Card title="Enregistrer un déploiement démo">
          <p className="muted">Réservé aux stratégies « validée MT5 ». Palier de risque 25 % (InpRiskScale = 0,25), puis 50 % et 100 % après 20 trades sans alerte.</p>
          <div className="row">
            <Field label="Révision validée MT5"><select value={rid} onChange={(e) => setRid(e.target.value)}>
              <option value="">{revs.data?.length ? "— choisir —" : "aucune révision validée MT5"}</option>{revs.data?.map((r) => <option key={r.id} value={r.id}>{r.id}</option>)}</select></Field>
            <Btn kind="primary" busy={a.busy} disabled={!rid} onClick={() => a.run(() => api.post("/demo/register", { revision_id: rid }), (r) => `Déploiement ${r.id} enregistré (magic ${r.magic}).`)}>Enregistrer</Btn>
          </div>
        </Card>
        <Card title="Déploiements" wide>
          <Table rows={data?.deployments ?? null} empty="Aucun déploiement démo." cols={[
            { k: "id", t: "ID" }, { k: "revision_id", t: "Révision" }, { k: "magic", t: "Magic" }, { k: "state", t: "État" },
            { k: "risk_stage", t: "Palier", f: (r) => <div style={{ display: "flex", gap: 6, alignItems: "center" }}><div className="progress" style={{ width: 60, minWidth: 60 }}><i style={{ width: `${r.risk_stage * 100}%` }} /></div>{fmt(r.risk_stage * 100, 0)} %</div> },
            { k: "server", t: "Serveur" },
            { k: "last_observation", t: "Dernière observation", f: (r) => r.last_observation ? `${r.last_observation.n_live} trades · ${r.last_observation.alerts.length} alerte(s)` : "—" },
            { k: "act", t: "Actions", f: (r) => <span className="actions">
              <button className="btn" onClick={() => a.run(() => api.post(`/demo/${r.id}/observe`), (x) => `Observation soumise (tâche ${x.task_id}).`)}>Observer</button>
              <button className="btn" onClick={() => a.run(() => api.post(`/demo/${r.id}/promote`), (x) => x.instruction)}>Palier suivant</button>
              <button className="btn danger" onClick={() => a.run(() => api.post(`/demo/${r.id}/suspend`, { on: true, reason: "suspension manuelle" }), () => "Suspendue.")}>Suspendre</button>
            </span> }]} />
        </Card>
        {deps.filter((x: any) => x.last_observation).map((x: any) => (
          <Card key={x.id} title={`Observation ${x.id}`}>
            {x.last_observation.alerts.map((al: string, i: number) => <div key={i} className="alert err">{al}</div>)}
            <Json v={x.last_observation.checks} />
          </Card>))}
      </div>
    </div>
  );
}
