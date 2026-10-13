import React, { useEffect, useState } from "react";
import { api } from "../api";
import { Badge, Btn, Card, Err, Field, fmt, Json, LineChart, Table, useAction, useApi, utc } from "../ui";
import { useNav } from "../main";

export function RevPicker() {
  const { nav, go } = useNav();
  const [v, setV] = useState(nav.rev ?? "");
  useEffect(() => setV(nav.rev ?? ""), [nav.rev]);
  return (
    <div className="row">
      <Field label="Révision de génome"><input style={{ width: 300 }} value={v} onChange={(e) => setV(e.target.value)} placeholder="rev_…" /></Field>
      <button className="btn" onClick={() => go({ ...nav, rev: v.trim() })}>Ouvrir</button>
    </div>
  );
}

export function DatasetCtx({ value, onChange }: { value: any; onChange: (v: any) => void }) {
  const ds = useApi<any[]>("/datasets");
  const base = ds.data?.find((d) => d.id === value.dataset_version_id);
  return (
    <div className="row">
      <Field label="Dataset">
        <select value={value.dataset_version_id ?? ""} onChange={(e) => onChange({ ...value, dataset_version_id: e.target.value, context: {} })}>
          <option value="">— choisir —</option>
          {ds.data?.map((d) => <option key={d.id} value={d.id}>{d.canonical_symbol} {d.timeframe} v{d.version}{d.synthetic ? " [SYNTH]" : ""}</option>)}
        </select>
      </Field>
      {ds.data?.filter((d) => base && d.canonical_symbol === base.canonical_symbol && d.timeframe !== base.timeframe).map((d) => (
        <label key={d.id}><input type="checkbox" checked={value.context?.[d.timeframe] === d.id}
          onChange={(e) => { const c = { ...(value.context ?? {}) }; if (e.target.checked) c[d.timeframe] = d.id; else delete c[d.timeframe]; onChange({ ...value, context: c }); }} /> contexte {d.timeframe}</label>))}
      <Field label="Spread fixe/plancher (points)"><input type="number" value={value.spread ?? ""} onChange={(e) => onChange({ ...value, spread: e.target.value })} /></Field>
      <Field label="Commission/lot/côté"><input type="number" step="0.01" value={value.commission ?? 0} onChange={(e) => onChange({ ...value, commission: Number(e.target.value) })} /></Field>
    </div>
  );
}

export const costOf = (v: any) => ({
  name: "ui", version: 1, spread_mode: "max", fixed_spread_points: v.spread === "" || v.spread == null ? null : Number(v.spread),
  commission_per_lot_side: v.commission ?? 0, slippage_points: 0, apply_swap: true,
  provenance: { spread: "assumed", commission: "assumed", slippage: "assumed", swap: "symbol_spec" },
});

export function GenomeExplorer() {
  const { nav, go } = useNav();
  const r = useApi(nav.rev ? `/genomes/${nav.rev}` : null, [nav.rev], true);
  const [txt, setTxt] = useState("");
  const [val, setVal] = useState<any>(null);
  const [ctx, setCtx] = useState<any>({});
  const a = useAction(), c = useAction(), adv = useAction();
  const d = r.data;
  return (
    <div>
      <h1>Explorateur de génome & généalogie</h1>
      <RevPicker />
      <Err msg={r.error} />
      <div className="grid">
        {d && <>
          <Card title={<>{d.id} <Badge s={d.status} /></>} actions={<>
            <button className="btn" onClick={() => go({ ...nav, screen: "passport" })}>Passeport</button>
            <button className="btn" onClick={() => go({ ...nav, screen: "backtests" })}>Backtest</button>
            <button className="btn" onClick={() => go({ ...nav, screen: "mt5" })}>MQL5</button>
          </>}>
            <dl className="kv rules">{Object.entries(d.description).map(([k, v]) => <React.Fragment key={k}><dt>{k}</dt><dd>{String(v)}</dd></React.Fragment>)}</dl>
            <p className="muted">Génome {d.genome_id} · révision {d.revision} · empreinte <code>{d.semantic_hash.slice(0, 16)}…</code></p>
            {d.export_blockers.length > 0 && <div className="alert warn">Export MQL5 bloqué : {d.export_blockers.join(" ; ")}</div>}
          </Card>
          <Card title="Généalogie (ascendants)">
            <Table rows={d.lineage} empty="Racine : aucun parent (génération initiale ou création manuelle)." onRow={(x) => go({ ...nav, rev: x.parent_id })} cols={[
              { k: "child_id", t: "Enfant" }, { k: "parent_id", t: "Parent" }, { k: "operator", t: "Opérateur" }, { k: "operator_version", t: "v" }]} />
          </Card>
          <Card title="Validation : faire progresser le statut" wide>
            <p className="muted">Filtrage → historique → robustesse → hors échantillon. Chaque étape exige des preuves ; un échec rejette la révision (preuve conservée).</p>
            <DatasetCtx value={ctx} onChange={setCtx} />
            <Btn kind="primary" busy={adv.busy} disabled={!ctx.dataset_version_id} onClick={() => adv.run(() => api.post(`/genomes/${d.id}/advance`, {
              dataset_version_id: ctx.dataset_version_id, context: ctx.context ?? {}, cost_profile: costOf(ctx), campaign_id: d.campaign_id,
            }), (x) => `Validation soumise (tâche ${x.task_id}).`)}>Lancer la validation</Btn>
            {adv.view}
            <h3>Historique des statuts</h3>
            <Table rows={d.transitions} empty="Aucune transition." cols={[{ k: "ts", t: "Date (UTC)" }, { k: "from_status", t: "De" },
              { k: "to_status", t: "Vers", f: (x) => <Badge s={x.to_status} /> }, { k: "criteria", t: "Critères", f: (x) => JSON.stringify(x.criteria).slice(0, 90) },
              { k: "evidence", t: "Preuves", f: (x) => Object.keys(x.evidence).join(", ") }]} />
          </Card>
          <Card title="Génome canonique (JSON)" wide><Json v={d.content} /></Card>
        </>}
        <Card title="Éditer / créer un génome" wide>
          <textarea rows={12} style={{ width: "100%" }} value={txt} onChange={(e) => setTxt(e.target.value)}
            placeholder='Coller un génome JSON (schéma qlab.genome/1.0), ou « Copier » depuis la révision ouverte.' />
          <div className="actions">
            {d && <button className="btn" onClick={() => setTxt(JSON.stringify(d.content, null, 2))}>Copier la révision ouverte</button>}
            <Btn busy={a.busy} onClick={() => a.run(async () => { const x = await api.post("/genomes/validate", { genome: JSON.parse(txt) }); setVal(x); return x; },
              (x) => x.valid ? "Génome valide." : `${x.errors.length} erreur(s).`)}>Valider</Btn>
            <Btn kind="primary" busy={c.busy} onClick={() => c.run(async () => { const x = await api.post("/genomes", { genome: JSON.parse(txt) }); go({ ...nav, rev: x.id }); return x; },
              (x) => `Révision ${x.id} créée (immuable).`)}>Créer la révision</Btn>
          </div>
          {a.view}{c.view}
          {val && !val.valid && <ul>{val.errors.map((e: string, i: number) => <li key={i} className="real-off">{e}</li>)}</ul>}
        </Card>
      </div>
    </div>
  );
}

export function Passport() {
  const { nav } = useNav();
  const [html, setHtml] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const ex = useAction();
  useEffect(() => {
    setHtml(null);
    if (!nav.rev) return;
    window.qlab.request("GET", `/api/v1/genomes/${nav.rev}/passport.html`).then((r) => r.status === 200 ? setHtml(r.data) : setErr(JSON.stringify(r.data)));
  }, [nav.rev]);
  return (
    <div>
      <h1>Passeport de stratégie</h1>
      <RevPicker />
      <Err msg={err} />
      {nav.rev && <div className="actions">
        <Btn busy={ex.busy} onClick={() => ex.run(() => api.post(`/genomes/${nav.rev}/export`), (r) => `Export soumis (tâche ${r.task_id}) ; l'archive apparaîtra dans le répertoire exports.`)}>Exporter (génome, passeport, EA, manifeste)</Btn>
      </div>}
      {ex.view}
      {html && <iframe className="passport" title="Passeport" sandbox="" srcDoc={html} />}
    </div>
  );
}

export function Backtests() {
  const { nav } = useNav();
  const [ctx, setCtx] = useState<any>({});
  const [seg, setSeg] = useState("research");
  const r = useApi(nav.rev ? `/genomes/${nav.rev}` : null, [nav.rev], true);
  const [evalSel, setEvalSel] = useState<any>(null);
  const trades = useApi(evalSel?.trades_artifact ? `/artifacts/${evalSel.trades_artifact}` : null, [evalSel?.id]);
  const a = useAction();
  const tr: any[] = (trades.data as any)?.trades ?? [];
  let eq = (evalSel?.metrics?.initial_equity ?? 10000);
  const curve = tr.map((t) => (eq += t.pnl));
  return (
    <div>
      <h1>Backtests & transactions</h1>
      <RevPicker />
      {nav.rev && <Card title="Lancer un backtest (moteur de référence)" wide>
        <DatasetCtx value={ctx} onChange={setCtx} />
        <Field label="Segment"><select value={seg} onChange={(e) => setSeg(e.target.value)}>
          <option value="research">entraînement + validation</option><option value="train">entraînement</option>
          <option value="validation">validation</option><option value="oos">hors échantillon (multiplicité tracée)</option>
        </select></Field>
        <Btn kind="primary" busy={a.busy} disabled={!ctx.dataset_version_id} onClick={() => a.run(() => api.post(`/genomes/${nav.rev}/backtest`, {
          dataset_version_id: ctx.dataset_version_id, context: ctx.context ?? {}, cost_profile: costOf(ctx), segment: seg,
        }), (x) => `Backtest soumis (tâche ${x.task_id}).`)}>Lancer</Btn>
        {a.view}
      </Card>}
      <Err msg={r.error} />
      {r.data && <Card title="Évaluations de cette révision" wide>
        <Table rows={(r.data as any).evaluations} onRow={setEvalSel} cols={[
          { k: "segment", t: "Segment" }, { k: "metrics.n_trades", t: "Trades", num: true }, { k: "metrics.net_profit", t: "Net", num: true },
          { k: "metrics.profit_factor", t: "PF", num: true }, { k: "metrics.sharpe", t: "Sharpe", num: true }, { k: "metrics.max_dd_pct", t: "DD %", num: true },
          { k: "metrics.expectancy_r", t: "Esp. R", num: true }, { k: "trades_artifact", t: "Trades conservés", f: (x) => x.trades_artifact ? "oui" : "non" },
          { k: "created_at", t: "Date (UTC)" }]} />
      </Card>}
      {evalSel && <div className="grid">
        <Card title="Métriques (après coûts)"><Json v={evalSel.metrics} /></Card>
        <Card title="Courbe de capital">
          {tr.length ? <LineChart xs={tr.map((t) => t.exit_ts)} ys={curve} unit="devise du compte" label={`equity de clôture — segment ${evalSel.segment}`} />
            : <p className="muted">Transactions non conservées pour cette évaluation (relancer avec conservation).</p>}
        </Card>
        {tr.length > 0 && <Card title={`${tr.length} transactions`} wide>
          <Table rows={tr.map((t, i) => ({ id: i, ...t }))} cols={[
            { k: "entry_ts", t: "Entrée (UTC)", f: (t) => utc(t.entry_ts) }, { k: "dir", t: "Sens", f: (t) => t.dir === 1 ? "long" : "short" },
            { k: "lots", t: "Lots", num: true }, { k: "entry", t: "Prix entrée", num: true, f: (t) => fmt(t.entry, 5) }, { k: "exit", t: "Prix sortie", num: true, f: (t) => fmt(t.exit, 5) },
            { k: "reason", t: "Motif" }, { k: "ambiguous", t: "Ambigu", f: (t) => t.ambiguous ? "oui" : "" }, { k: "r", t: "R", num: true },
            { k: "commission", t: "Comm.", num: true }, { k: "swap", t: "Swap", num: true }, { k: "pnl", t: "PnL net", num: true }, { k: "bars_held", t: "Barres", num: true }]} />
        </Card>}
      </div>}
    </div>
  );
}
