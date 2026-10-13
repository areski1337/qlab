import React, { useEffect, useMemo, useState } from "react";
import { api } from "../api";
import { Badge, Btn, Card, Err, Field, fmt, PageHead, Seg, Table, Tile, useAction, useApi } from "../ui";
import { Bars, Explain, Lines, Scatter } from "../charts";
import { useNav } from "../main";

const TRIBES = [["consistency", "Consistance"], ["growth", "Croissance"], ["exploration", "Exploration"], ["specialization", "Spécialisation"]];
const TRIBE_FR: Record<string, string> = { ...Object.fromEntries(TRIBES), merge: "Fusion" };
const SESSIONS = ["london_kz", "ny_am_kz", "asia_kz", "london_close_kz", "london", "new_york", "tokyo", "ldn_ny_overlap"];
const METRIC_FR: Record<string, string> = {
  sharpe: "Sharpe", max_dd_pct: "Drawdown max %", net_profit: "Profit net", return_pct: "Rendement %", profit_factor: "Profit factor",
  expectancy_r: "Espérance (R)", win_rate: "Taux de réussite", n_trades: "Trades", r2_equity: "Régularité (R² equity)",
};

export function Campaigns() {
  const { go } = useNav();
  const ds = useApi<any[]>("/datasets", [], true);
  const camps = useApi<any[]>("/campaigns", [], true);
  const a = useAction();
  const [extra, setExtra] = useState<string[]>([]);
  const [f, setF] = useState<any>({
    name: "Campagne", dataset_version_id: "", ctx: "", tribes: ["consistency", "growth", "exploration", "specialization"],
    specialization_session: "london_kz", population: 24, generations_per_tribe: 20, merge_generations: 8, seed: 42, workers: 4,
    sides: "both", spread: "", commission: 0, slippage: 0, min_trades: 30, max_dd_pct: 30, max_ambiguous_ratio: 0.3,
  });
  const set = (k: string) => (e: any) => setF({ ...f, [k]: e.target.type === "number" ? Number(e.target.value) : e.target.value });
  const base = ds.data?.find((d) => d.id === f.dataset_version_id);
  const htfs = ds.data?.filter((d) => base && d.canonical_symbol === base.canonical_symbol && d.timeframe !== base.timeframe) ?? [];
  const evals = f.tribes.length * f.population * f.generations_per_tribe + f.population * f.merge_generations;
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
    // campagnes supplémentaires : mêmes réglages, un dataset par symbole (sans contexte HTF spécifique)
    for (const d of extra) await api.post("/campaigns", { config: { ...cfg, name: `${f.name} · ${ds.data!.find((x) => x.id === d)?.canonical_symbol}`, dataset_version_id: d, context_version_ids: {} } });
    go({ screen: "lab", campaign: r.campaign_id });
    return r;
  });
  return (
    <div>
      <PageHead title="Campagnes" sub="Recherche génétique multi-tribus sur entraînement + validation. Les segments hors échantillon et final restent scellés." />
      <div className="grid">
        <Card title="Nouvelle campagne génétique" wide actions={<span className="muted" style={{ fontFamily: "var(--font-num)" }}>≈ {fmt(evals, 0)} évaluations prévues</span>}>
          <h3>Marché</h3>
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
            <Field label="Lancer aussi sur (multi-symboles)">
              <select multiple size={3} value={extra} onChange={(e) => setExtra(Array.from(e.target.selectedOptions).map((o) => o.value))}>
                {ds.data?.filter((d) => base && d.timeframe === base.timeframe && d.id !== base.id).map((d) => <option key={d.id} value={d.id}>{d.canonical_symbol} {d.timeframe} v{d.version}</option>)}
              </select>
            </Field>
            <Field label="Côtés"><Seg label="Côtés" value={f.sides} onChange={(v) => setF({ ...f, sides: v })} options={[["both", "Long + short"], ["long", "Long"], ["short", "Short"]]} /></Field>
          </div>
          <h3>Tribus</h3>
          <div className="row">
            {TRIBES.map(([k, l]) => (
              <label key={k}><input type="checkbox" checked={f.tribes.includes(k)}
                onChange={(e) => setF({ ...f, tribes: e.target.checked ? [...f.tribes, k] : f.tribes.filter((x: string) => x !== k) })} /> {l}</label>))}
            <Field label="Session de spécialisation"><select value={f.specialization_session} onChange={set("specialization_session")}>{SESSIONS.map((s) => <option key={s}>{s}</option>)}</select></Field>
          </div>
          <h3>Effort de recherche</h3>
          <div className="row">
            <Field label="Population / tribu"><input type="number" min={4} max={500} value={f.population} onChange={set("population")} /></Field>
            <Field label="Générations / tribu"><input type="number" min={1} max={500} value={f.generations_per_tribe} onChange={set("generations_per_tribe")} /></Field>
            <Field label="Générations de fusion"><input type="number" min={0} max={200} value={f.merge_generations} onChange={set("merge_generations")} /></Field>
            <Field label="Graine"><input type="number" value={f.seed} onChange={set("seed")} /></Field>
            <Field label="Processus parallèles"><input type="number" min={0} max={64} value={f.workers} onChange={set("workers")} /></Field>
          </div>
          <h3>Coûts et contraintes</h3>
          <div className="row">
            <Field label="Spread fixe/plancher (points)" hint="requis si le spread historique est nul ; hypothèse"><input type="number" value={f.spread} onChange={set("spread")} placeholder="ex. 35" /></Field>
            <Field label="Commission / lot / côté"><input type="number" step="0.01" value={f.commission} onChange={set("commission")} /></Field>
            <Field label="Glissement (points)"><input type="number" value={f.slippage} onChange={set("slippage")} /></Field>
            <Field label="Trades min (train)"><input type="number" value={f.min_trades} onChange={set("min_trades")} /></Field>
            <Field label="DD max %"><input type="number" value={f.max_dd_pct} onChange={set("max_dd_pct")} /></Field>
          </div>
          <div className="actions">
            <Btn kind="primary" busy={a.busy} disabled={!f.dataset_version_id || !f.tribes.length} onClick={submit}>Lancer la campagne{extra.length ? ` (+${extra.length})` : ""}</Btn>
            <span className="muted">Aucune campagne ne peut envoyer d'ordre.</span>
          </div>
          {a.view}
        </Card>
        <Card title="Campagnes" wide>
          <Err msg={camps.error} />
          <Table rows={camps.data} onRow={(r) => go({ screen: "lab", campaign: r.id })} cols={[
            { k: "name", t: "Nom", f: (r) => <b>{r.name}</b> }, { k: "id", t: "ID" }, { k: "task_state", t: "État", f: (r) => <Badge s={r.task_state} /> },
            { k: "progress", t: "Progression", f: (r) => <div style={{ display: "flex", gap: 8, alignItems: "center", minWidth: 140 }}><div className="progress" style={{ flex: 1 }}><i style={{ width: `${r.progress * 100}%` }} /></div>{fmt(r.progress * 100, 0)} %</div> },
            { k: "n_candidates", t: "Candidats", num: true }, { k: "created_at", t: "Créée (UTC)" }]} />
        </Card>
      </div>
    </div>
  );
}

function CampaignPicker() {
  const { nav, go } = useNav();
  const camps = useApi<any[]>("/campaigns", [], true);
  useEffect(() => { if (!nav.campaign && camps.data?.length) go({ ...nav, campaign: camps.data[0].id }); }, [camps.data]);
  return (
    <select aria-label="Campagne" value={nav.campaign ?? ""} onChange={(e) => go({ ...nav, campaign: e.target.value })}>
      <option value="">— campagne —</option>
      {camps.data?.map((c) => <option key={c.id} value={c.id}>{c.name} · {c.id}</option>)}
    </select>
  );
}

export function CampaignLab() {
  const { nav } = useNav();
  const c = useApi(nav.campaign ? `/campaigns/${nav.campaign}` : null, [nav.campaign], true);
  const a = useAction();
  const [norm, setNorm] = useState<"abs" | "norm">("abs");
  const d = c.data;
  const hist: any[] = d?.state_snapshot?.history ?? [];
  const byTribe = useMemo(() => {
    const m: Record<string, any[]> = {};
    for (const h of hist) (m[h.tribe] ??= []).push(h);
    return m;
  }, [hist]);
  const tribes = Object.keys(byTribe);
  const ops = Object.entries(d?.state_snapshot?.op_stats ?? {}).map(([k, v]: any) => ({ id: k, op: k, tries: v[0], ok: v[1], rate: v[0] ? v[1] / v[0] : null }));
  const act = (x: string) => a.run(() => api.post(`/tasks/${d.task_id}/${x}`), () => `Action « ${x} » appliquée`);
  const last = (t: string) => byTribe[t]?.[byTribe[t].length - 1];
  return (
    <div>
      <PageHead title="Laboratoire génétique" sub="Suivi en direct de l'évolution : convergence, diversité, efficacité des opérateurs.">
        <CampaignPicker />
      </PageHead>
      <Err msg={c.error} />
      {!d && !c.error && <p className="muted">Choisir une campagne.</p>}
      {d && <>
        <div className="tiles">
          <Tile l="État" v={<Badge s={d.task.state} />} s={`${d.state_snapshot?.phase ?? "pas encore démarrée"} · génération ${d.state_snapshot?.gen ?? 0}`} />
          <Tile l="Progression" v={`${fmt(d.task.progress * 100, 0)} %`} s={<div className="progress"><i style={{ width: `${d.task.progress * 100}%` }} /></div>} />
          <Tile l="Candidats" v={fmt(d.n_candidates, 0)} s="révisions générées" />
          <Tile l="Évaluations" v={fmt(d.n_evaluations, 0)} s="backtests exécutés" />
          <Tile l="Front final" v={fmt(d.task.result?.front?.length ?? 0, 0)} s="non dominés après fusion" />
        </div>
        <div className="grid">
          <Card title={d.name} wide actions={<>
            <Btn busy={a.busy} disabled={!["queued", "running"].includes(d.task.state)} onClick={() => act("pause")}>Pause</Btn>
            <Btn busy={a.busy} disabled={d.task.state !== "paused"} onClick={() => act("resume")}>Reprendre</Btn>
            <Btn kind="danger" busy={a.busy} disabled={["completed", "cancelled", "failed"].includes(d.task.state) || d.task.state === "running"} onClick={() => act("cancel")}>Annuler</Btn>
          </>}>
            {a.view}
            {d.task.error && <div className="alert err">{d.task.error}</div>}
            {d.task.result?.warning && <div className="alert warn">{d.task.result.warning}</div>}
            <div className="chartbar"><Seg label="Échelle" value={norm} onChange={setNorm} options={[["abs", "Valeurs"], ["norm", "Normalisée 0–1 par tribu"]]} /></div>
            <Lines xl="génération" unit="meilleur objectif" series={tribes.map((t) => {
              const ys = byTribe[t].map((h) => h.best_obj).filter(Number.isFinite) as number[];
              const lo = Math.min(...ys), hi = Math.max(...ys);
              return { name: TRIBE_FR[t] ?? t, pts: byTribe[t].map((h, i) => ({ x: h.gen ?? i, y: h.best_obj == null ? NaN : norm === "norm" ? (hi > lo ? (h.best_obj - lo) / (hi - lo) : 1) : h.best_obj })) };
            })} height={260} />
            <Explain>Chaque courbe = <b>meilleur objectif principal</b> parmi les stratégies faisables d'une tribu, génération après génération. Une courbe qui monte puis s'aplatit = convergence ; un plateau long déclenche les mécanismes anti-stagnation. Les objectifs diffèrent selon la tribu : la vue « normalisée » compare les dynamiques. Le meilleur score observé est biaisé à la hausse : seule la validation tranche.</Explain>
          </Card>
          <Card title="Diversité des tribus (dernière génération)">
            <Bars unit="indice" items={tribes.flatMap((t) => [
              { label: `${(TRIBE_FR[t] ?? t).slice(0, 5)}·struct`, value: last(t)?.diversity?.structural ?? null, tip: "diversité structurelle (règles différentes)" },
              { label: `${(TRIBE_FR[t] ?? t).slice(0, 5)}·comp`, value: last(t)?.diversity?.behavioral ?? null, tip: "diversité comportementale (trades différents)", muted: true },
            ])} />
            <Explain>Plus c'est haut, plus la population explore des idées différentes. Une diversité qui s'effondre = population qui se clone : risque de surapprentissage sur une seule idée.</Explain>
            <dl className="kv" style={{ marginTop: 8 }}>{tribes.map((t) => <React.Fragment key={t}><dt>{TRIBE_FR[t] ?? t}</dt>
              <dd>lignées {last(t)?.diversity?.lineages ?? "—"} · stagnation niveau {last(t)?.stagnation_level ?? "—"} · faisables {last(t)?.feasible ?? "—"}</dd></React.Fragment>)}</dl>
          </Card>
          <Card title="Efficacité des opérateurs">
            <Bars unit="% de succès" items={ops.sort((x, y) => (y.rate ?? 0) - (x.rate ?? 0)).map((o) => ({ label: o.op.slice(0, 10), value: o.rate == null ? null : o.rate * 100, tip: `${o.op}\n${o.ok} succès / ${o.tries} essais` }))} />
            <Explain>Part des enfants produits par un opérateur qui sont <b>faisables et sur le premier front de Pareto</b> de leur génération (a priori des campagnes passées inclus). La campagne tire plus souvent les opérateurs efficaces (mémoire des opérateurs).</Explain>
          </Card>
          {d.task.result?.front && <Card title="Front de Pareto final (fusion)" wide><FrontTable front={d.task.result.front} /></Card>}
        </div>
      </>}
    </div>
  );
}

function FrontTable({ front }: { front: any[] }) {
  const { go } = useNav();
  return <Table rows={front.map((f) => ({ id: f.revision_id, ...f }))} onRow={(r) => go({ screen: "genome", rev: r.id })} cols={[
    { k: "id", t: "Révision" }, { k: "train.n_trades", t: "Trades train", num: true }, { k: "train.sharpe", t: "Sharpe train", num: true, tone: true },
    { k: "validation.sharpe", t: "Sharpe valid.", num: true, tone: true }, { k: "train.max_dd_pct", t: "DD % train", num: true },
    { k: "validation.max_dd_pct", t: "DD % valid.", num: true }, { k: "validation.net_profit", t: "Net valid.", num: true, tone: true }]} />;
}

export function Pareto() {
  const { nav, go } = useNav();
  const [seg, setSeg] = useState<"train" | "validation">("train");
  const [xk, setXk] = useState("max_dd_pct");
  const [yk, setYk] = useState("sharpe");
  const c = useApi<any[]>(nav.campaign ? `/campaigns/${nav.campaign}/candidates?segment=${seg}&limit=5000` : null, [nav.campaign, seg], true);
  const pts = (c.data ?? []).map((r) => ({ id: r.id, x: r.metrics[xk], y: r.metrics[yk], front: r.status !== "unverified" && r.status !== "rejected" }));
  const keys = Object.keys(METRIC_FR);
  const kept = pts.filter((p) => p.front).length;
  const sharpes = (c.data ?? []).map((r) => r.metrics.sharpe).filter(Number.isFinite);
  return (
    <div>
      <PageHead title="Comparaison & front de Pareto" sub="Tous les candidats évalués, y compris rejetés : rien n'est masqué.">
        <CampaignPicker />
        <Seg label="Segment" value={seg} onChange={setSeg} options={[["train", "Entraînement"], ["validation", "Validation"]]} />
      </PageHead>
      <Err msg={c.error} />
      <div className="tiles">
        <Tile l="Candidats" v={fmt(c.data?.length ?? 0, 0)} s={`segment ${seg === "train" ? "entraînement" : "validation"}`} />
        <Tile l="Retenus" v={fmt(kept, 0)} s="statut ≥ filtrée" tone={kept ? "good" : null} />
        <Tile l="Meilleur Sharpe" v={sharpes.length ? fmt(Math.max(...sharpes), 2) : "—"} s="biaisé à la hausse (sélection)" />
      </div>
      <div className="grid">
        <Card title="Carte des compromis" wide actions={<>
          <select aria-label="Axe X" value={xk} onChange={(e) => setXk(e.target.value)}>{keys.map((k) => <option key={k} value={k}>X : {METRIC_FR[k]}</option>)}</select>
          <select aria-label="Axe Y" value={yk} onChange={(e) => setYk(e.target.value)}>{keys.map((k) => <option key={k} value={k}>Y : {METRIC_FR[k]}</option>)}</select>
        </>}>
          <Scatter pts={pts} xl={METRIC_FR[xk]} yl={METRIC_FR[yk]} onPick={(id) => go({ ...nav, screen: "genome", rev: id })} />
          <Explain>Chaque point est une stratégie. En <b>accent vif</b> : retenues (statut ≥ filtrée). Avec X = drawdown et Y = Sharpe, les meilleures sont <b>en haut à gauche</b> (plus de rendement par unité de risque, pertes plus faibles). Cliquer ouvre la stratégie.</Explain>
        </Card>
        <Card title={`${c.data?.length ?? 0} candidats`} wide>
          <Table rows={c.data} onRow={(r) => go({ ...nav, screen: "genome", rev: r.id })} cols={[
            { k: "id", t: "Révision" }, { k: "status", t: "Statut", f: (r) => <Badge s={r.status} /> },
            ...keys.map((k) => ({ k: `metrics.${k}`, t: METRIC_FR[k], num: true, tone: ["sharpe", "net_profit", "return_pct", "expectancy_r"].includes(k) }))]} />
        </Card>
      </div>
    </div>
  );
}
