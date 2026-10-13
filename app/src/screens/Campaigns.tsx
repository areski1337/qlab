import React, { useMemo, useState } from "react";
import { api } from "../api";
import { Badge, Btn, Card, Err, Field, fmt, Json, LineChart, Scatter, Table, useAction, useApi } from "../ui";
import { useNav } from "../main";

const TRIBES = [["consistency", "Consistance"], ["growth", "Croissance"], ["exploration", "Exploration"], ["specialization", "Spécialisation"]];
const SESSIONS = ["london_kz", "ny_am_kz", "asia_kz", "london_close_kz", "london", "new_york", "tokyo", "ldn_ny_overlap"];

export function Campaigns() {
  const { go } = useNav();
  const ds = useApi<any[]>("/datasets", [], true);
  const camps = useApi<any[]>("/campaigns", [], true);
  const a = useAction();
  const [f, setF] = useState<any>({
    name: "Campagne", dataset_version_id: "", ctx: "", tribes: ["consistency", "growth", "exploration", "specialization"],
    specialization_session: "london_kz", population: 24, generations_per_tribe: 20, merge_generations: 8, seed: 42, workers: 4,
    sides: "both", spread: "", commission: 0, slippage: 0, min_trades: 30, max_dd_pct: 30, max_ambiguous_ratio: 0.3,
  });
  const set = (k: string) => (e: any) => setF({ ...f, [k]: e.target.type === "number" ? Number(e.target.value) : e.target.value });
  const base = ds.data?.find((d) => d.id === f.dataset_version_id);
  const htfs = ds.data?.filter((d) => base && d.canonical_symbol === base.canonical_symbol && d.timeframe !== base.timeframe) ?? [];
  const submit = () => a.run(async () => {
    const cfg: any = {
      name: f.name, dataset_version_id: f.dataset_version_id, seed: f.seed, population: f.population,
      generations_per_tribe: f.generations_per_tribe, merge_generations: f.merge_generations, tribes: f.tribes,
      specialization_session: f.specialization_session, workers: f.workers, sides: f.sides,
      context_version_ids: f.ctx ? { [ds.data!.find((d) => d.id === f.ctx).timeframe]: f.ctx } : {},
      constraints: { min_trades: f.min_trades, max_dd_pct: f.max_dd_pct, max_ambiguous_ratio: f.max_ambiguous_ratio },
      cost_profile: {
        name: "ui", version: 1, spread_mode: "max", fixed_spread_points: f.spread === "" ? null : Number(f.spread),
        commission_per_lot_side: f.commission, slippage_points: f.slippage, apply_swap: true,
        provenance: { spread: "assumed", commission: "assumed", slippage: "assumed", swap: "symbol_spec" },
      },
    };
    const r = await api.post("/campaigns", { config: cfg });
    go({ screen: "lab", campaign: r.campaign_id });
    return r;
  });
  return (
    <div>
      <h1>Campagnes</h1>
      <div className="grid">
        <Card title="Nouvelle campagne génétique" wide>
          <div className="row">
            <Field label="Nom"><input value={f.name} onChange={set("name")} /></Field>
            <Field label="Dataset d'exécution">
              <select value={f.dataset_version_id} onChange={set("dataset_version_id")}>
                <option value="">— choisir —</option>
                {ds.data?.map((d) => <option key={d.id} value={d.id}>{d.canonical_symbol} {d.timeframe} v{d.version} ({fmt(d.n_bars, 0)} barres){d.synthetic ? " [SYNTHÉTIQUE]" : ""}</option>)}
              </select>
            </Field>
            <Field label="Contexte HTF (optionnel)">
              <select value={f.ctx} onChange={set("ctx")}>
                <option value="">aucun</option>
                {htfs.map((d) => <option key={d.id} value={d.id}>{d.timeframe} v{d.version}</option>)}
              </select>
            </Field>
            <Field label="Côtés"><select value={f.sides} onChange={set("sides")}><option value="both">long + short</option><option value="long">long</option><option value="short">short</option></select></Field>
          </div>
          <div className="row">
            {TRIBES.map(([k, l]) => (
              <label key={k}><input type="checkbox" checked={f.tribes.includes(k)}
                onChange={(e) => setF({ ...f, tribes: e.target.checked ? [...f.tribes, k] : f.tribes.filter((x: string) => x !== k) })} /> {l}</label>))}
            <Field label="Session de spécialisation"><select value={f.specialization_session} onChange={set("specialization_session")}>{SESSIONS.map((s) => <option key={s}>{s}</option>)}</select></Field>
          </div>
          <div className="row">
            <Field label="Population / tribu"><input type="number" min={4} max={500} value={f.population} onChange={set("population")} /></Field>
            <Field label="Générations / tribu"><input type="number" min={1} max={500} value={f.generations_per_tribe} onChange={set("generations_per_tribe")} /></Field>
            <Field label="Générations de fusion"><input type="number" min={0} max={200} value={f.merge_generations} onChange={set("merge_generations")} /></Field>
            <Field label="Graine"><input type="number" value={f.seed} onChange={set("seed")} /></Field>
            <Field label="Processus parallèles"><input type="number" min={0} max={64} value={f.workers} onChange={set("workers")} /></Field>
          </div>
          <div className="row">
            <Field label="Spread fixe/plancher (points)" hint="requis si le spread historique est nul ; hypothèse"><input type="number" value={f.spread} onChange={set("spread")} placeholder="ex. 35" /></Field>
            <Field label="Commission / lot / côté"><input type="number" step="0.01" value={f.commission} onChange={set("commission")} /></Field>
            <Field label="Glissement (points)"><input type="number" value={f.slippage} onChange={set("slippage")} /></Field>
            <Field label="Trades min (train)"><input type="number" value={f.min_trades} onChange={set("min_trades")} /></Field>
            <Field label="DD max %"><input type="number" value={f.max_dd_pct} onChange={set("max_dd_pct")} /></Field>
          </div>
          <p className="muted">La campagne n'utilise que les segments entraînement et validation. Les segments hors échantillon et final restent inaccessibles à la recherche. Aucune campagne ne peut envoyer d'ordre.</p>
          <Btn kind="primary" busy={a.busy} disabled={!f.dataset_version_id || !f.tribes.length} onClick={submit}>Lancer la campagne</Btn>
          {a.view}
        </Card>
        <Card title="Campagnes" wide>
          <Err msg={camps.error} />
          <Table rows={camps.data} onRow={(r) => go({ screen: "lab", campaign: r.id })} cols={[
            { k: "name", t: "Nom" }, { k: "id", t: "ID" }, { k: "task_state", t: "État", f: (r) => <Badge s={r.task_state} /> },
            { k: "progress", t: "Progression", f: (r) => `${fmt(r.progress * 100, 0)} %` }, { k: "n_candidates", t: "Candidats", num: true },
            { k: "created_at", t: "Créée (UTC)" }]} />
        </Card>
      </div>
    </div>
  );
}

function CampaignPicker() {
  const { nav, go } = useNav();
  const camps = useApi<any[]>("/campaigns", [], true);
  return (
    <select value={nav.campaign ?? ""} onChange={(e) => go({ ...nav, campaign: e.target.value })}>
      <option value="">— campagne —</option>
      {camps.data?.map((c) => <option key={c.id} value={c.id}>{c.name} · {c.id}</option>)}
    </select>
  );
}

export function CampaignLab() {
  const { nav } = useNav();
  const c = useApi(nav.campaign ? `/campaigns/${nav.campaign}` : null, [nav.campaign], true);
  const a = useAction();
  const d = c.data;
  const hist: any[] = d?.state_snapshot?.history ?? [];
  const byTribe = useMemo(() => {
    const m: Record<string, any[]> = {};
    for (const h of hist) (m[h.tribe] ??= []).push(h);
    return m;
  }, [hist]);
  const act = (x: string) => a.run(() => api.post(`/tasks/${d.task_id}/${x}`), () => `Action « ${x} » appliquée`);
  return (
    <div>
      <h1>Laboratoire génétique</h1>
      <div className="row"><CampaignPicker /></div>
      <Err msg={c.error} />
      {d && <div className="grid">
        <Card title={<>{d.name} <Badge s={d.task.state} /></>} actions={<>
          <Btn busy={a.busy} disabled={!["queued", "running"].includes(d.task.state)} onClick={() => act("pause")}>Pause</Btn>
          <Btn busy={a.busy} disabled={d.task.state !== "paused"} onClick={() => act("resume")}>Reprendre</Btn>
          <Btn kind="danger" busy={a.busy} disabled={["completed", "cancelled", "failed"].includes(d.task.state) || d.task.state === "running"} onClick={() => act("cancel")}>Annuler</Btn>
        </>}>
          {a.view}
          <div className="progress"><i style={{ width: `${d.task.progress * 100}%` }} /></div>
          <dl className="kv">
            <dt>Phase</dt><dd>{d.state_snapshot?.phase ?? "pas encore démarrée"} · génération {d.state_snapshot?.gen ?? 0}</dd>
            <dt>Candidats générés</dt><dd>{fmt(d.n_candidates, 0)}</dd>
            <dt>Évaluations</dt><dd>{fmt(d.n_evaluations, 0)}</dd>
            <dt>Populations</dt><dd>{JSON.stringify(d.state_snapshot?.populations ?? {})}</dd>
            <dt>Archives</dt><dd>{JSON.stringify(d.state_snapshot?.archives ?? {})}</dd>
            <dt>Erreur</dt><dd>{d.task.error ?? "—"}</dd>
          </dl>
          {d.task.result?.warning && <div className="alert warn">{d.task.result.warning}</div>}
        </Card>
        <Card title="Mémoire des opérateurs (taux de succès)">
          <Table rows={Object.entries(d.state_snapshot?.op_stats ?? {}).map(([k, v]: any) => ({ id: k, op: k, tries: v[0], ok: v[1], rate: v[0] ? v[1] / v[0] : null }))}
            cols={[{ k: "op", t: "Opérateur" }, { k: "tries", t: "Essais", num: true }, { k: "ok", t: "Succès", num: true }, { k: "rate", t: "Taux", num: true, f: (r) => r.rate == null ? "—" : `${fmt(r.rate * 100, 1)} %` }]} />
        </Card>
        {Object.entries(byTribe).map(([t, hs]) => (
          <Card key={t} title={`Tribu ${t} : meilleur 1er objectif par génération`}>
            <LineChart xs={hs.map((h: any) => Date.parse(h.ts) / 1000)} ys={hs.map((h: any) => h.best_obj ?? NaN).filter(Number.isFinite)} unit="objectif" label={`${t} — objectif principal (faisables)`} height={160} />
            <p className="muted">Diversité structurelle {fmt(hs.at(-1)?.diversity?.structural, 2)} · comportementale {fmt(hs.at(-1)?.diversity?.behavioral, 2)} · lignées {hs.at(-1)?.diversity?.lineages} · stagnation niveau {hs.at(-1)?.stagnation_level}</p>
          </Card>))}
        {d.task.result?.front && <Card title="Front de Pareto final (fusion)" wide>
          <FrontTable front={d.task.result.front} />
        </Card>}
      </div>}
    </div>
  );
}

function FrontTable({ front }: { front: any[] }) {
  const { go } = useNav();
  return <Table rows={front.map((f) => ({ id: f.revision_id, ...f }))} onRow={(r) => go({ screen: "genome", rev: r.id })} cols={[
    { k: "id", t: "Révision" }, { k: "train.n_trades", t: "Trades train", num: true }, { k: "train.sharpe", t: "Sharpe train", num: true },
    { k: "validation.sharpe", t: "Sharpe valid.", num: true }, { k: "train.max_dd_pct", t: "DD % train", num: true },
    { k: "validation.max_dd_pct", t: "DD % valid.", num: true }, { k: "validation.net_profit", t: "Net valid.", num: true }]} />;
}

export function Pareto() {
  const { nav, go } = useNav();
  const [seg, setSeg] = useState("train");
  const [xk, setXk] = useState("max_dd_pct");
  const [yk, setYk] = useState("sharpe");
  const c = useApi<any[]>(nav.campaign ? `/campaigns/${nav.campaign}/candidates?segment=${seg}` : null, [nav.campaign, seg], true);
  const pts = (c.data ?? []).map((r) => ({ id: r.id, x: r.metrics[xk], y: r.metrics[yk], front: r.status !== "unverified" && r.status !== "rejected" }));
  const keys = ["sharpe", "max_dd_pct", "net_profit", "return_pct", "profit_factor", "expectancy_r", "win_rate", "n_trades", "r2_equity"];
  return (
    <div>
      <h1>Comparaison des stratégies & front de Pareto</h1>
      <div className="row">
        <CampaignPicker />
        <Field label="Segment"><select value={seg} onChange={(e) => setSeg(e.target.value)}><option value="train">entraînement</option><option value="validation">validation</option></select></Field>
        <Field label="Axe X"><select value={xk} onChange={(e) => setXk(e.target.value)}>{keys.map((k) => <option key={k}>{k}</option>)}</select></Field>
        <Field label="Axe Y"><select value={yk} onChange={(e) => setYk(e.target.value)}>{keys.map((k) => <option key={k}>{k}</option>)}</select></Field>
      </div>
      <Err msg={c.error} />
      <div className="alert warn">Tous les candidats évalués sont affichés, y compris rejetés. Le meilleur point observé est biaisé à la hausse (biais de sélection) ; en orange : candidats retenus (statut ≥ filtrée).</div>
      <Card wide><Scatter pts={pts} xl={xk} yl={yk} onPick={(id) => go({ ...nav, screen: "genome", rev: id })} /></Card>
      <Card title={`${c.data?.length ?? 0} candidats`} wide>
        <Table rows={c.data} onRow={(r) => go({ ...nav, screen: "genome", rev: r.id })} cols={[
          { k: "id", t: "Révision" }, { k: "status", t: "Statut", f: (r) => <Badge s={r.status} /> },
          ...keys.map((k) => ({ k: `metrics.${k}`, t: k, num: true }))]} />
      </Card>
    </div>
  );
}

