import React, { useState } from "react";
import { api } from "../api";
import { Badge, Btn, Card, Err, Field, fmt, Json, Table, useAction, useApi } from "../ui";
import { useNav } from "../main";
import { costOf, DatasetCtx, RevPicker } from "./Genome";

export function Mt5() {
  const { nav } = useNav();
  const ea = useApi<any[]>(nav.rev ? `/genomes/${nav.rev}/ea` : null, [nav.rev], true);
  const [ctx, setCtx] = useState<any>({});
  const [p, setP] = useState({ from: "2026.08.01", to: "2026.10.01", model: 1 });
  const [rep, setRep] = useState<any>(null);
  const a = useAction();
  return (
    <div>
      <h1>Compilation MQL5 & validation MT5</h1>
      <RevPicker />
      <div className="alert warn">Une compilation réussie ne prouve pas la parité ; une parité historique ne garantit pas la rentabilité. Le Strategy Tester en ligne de commande exige que le terminal MT5 soit fermé : sinon l'étape est signalée « bloquée ».</div>
      {nav.rev && <Card title="Générer, compiler (MetaEditor réel) et comparer au Strategy Tester" wide>
        <DatasetCtx value={ctx} onChange={setCtx} />
        <div className="row">
          <Field label="Du (AAAA.MM.JJ)"><input value={p.from} onChange={(e) => setP({ ...p, from: e.target.value })} /></Field>
          <Field label="Au (AAAA.MM.JJ)"><input value={p.to} onChange={(e) => setP({ ...p, to: e.target.value })} /></Field>
          <Field label="Modèle de ticks"><select value={p.model} onChange={(e) => setP({ ...p, model: Number(e.target.value) })}>
            <option value={1}>OHLC M1</option><option value={0}>Tous les ticks (générés)</option><option value={4}>Ticks réels</option></select></Field>
        </div>
        <Btn kind="primary" busy={a.busy} disabled={!ctx.dataset_version_id} onClick={() => a.run(() => api.post(`/genomes/${nav.rev}/mt5-verify`, {
          dataset_version_id: ctx.dataset_version_id, context: ctx.context ?? {}, cost_profile: costOf(ctx), ...p,
        }), (x) => `Vérification soumise (tâche ${x.task_id}).`)}>Lancer la vérification</Btn>
        {a.view}
      </Card>}
      <Err msg={ea.error} />
      {ea.data?.map((e) => (
        <Card key={e.id} wide title={<>EA {e.id} · générateur {e.generator_version}</>}>
          <p className="muted">Source <code>{e.source_sha256.slice(0, 16)}…</code> · fuseau {e.tz_profile} · limites de risque <code>{e.risk_limits_sha256.slice(0, 12)}…</code></p>
          <h3>Compilations</h3>
          <Table rows={e.compilations} cols={[{ k: "created_at", t: "Date (UTC)" }, { k: "status", t: "Statut", f: (r) => <Badge s={r.status === "succeeded" ? "completed" : r.status === "blocked" ? "paused" : "failed"} /> },
            { k: "errors", t: "Erreurs", num: true }, { k: "warnings", t: "Avert.", num: true }, { k: "diagnostic", t: "Diagnostic" }]} />
          <h3>Parité</h3>
          <Table rows={e.parity} onRow={setRep} cols={[{ k: "created_at", t: "Date (UTC)" }, { k: "status", t: "Statut" }, { k: "grade", t: "Note" },
            { k: "critical", t: "Critique", f: (r) => r.critical == null ? "—" : r.critical ? "OUI" : "non" },
            { k: "report.trades.match_ratio", t: "Trades appariés", f: (r) => r.report ? `${fmt(r.report.trades.match_ratio * 100, 1)} %` : "—" },
            { k: "report.signals.agreement", t: "Signaux", f: (r) => r.report ? `${fmt(r.report.signals.agreement * 100, 1)} %` : "—" },
            { k: "diagnostic", t: "Diagnostic" }]} />
        </Card>))}
      {rep?.report && <Card title={`Rapport de parité — note ${rep.grade}`} wide>
        {rep.report.critical_reasons?.map((x: string, i: number) => <div key={i} className="alert err">{x}</div>)}
        <dl className="kv">
          <dt>Signaux</dt><dd>réf. {rep.report.signals.ref} · MT5 {rep.report.signals.mt5} · concordance {fmt(rep.report.signals.agreement * 100, 2)} %</dd>
          <dt>Trades</dt><dd>réf. {rep.report.trades.ref} · MT5 {rep.report.trades.mt5} · appariés {rep.report.trades.matched}</dd>
          <dt>Écarts médians</dt><dd>entrée {fmt(rep.report.prices.median_abs_entry_diff_pts)} pts · sortie {fmt(rep.report.prices.median_abs_exit_diff_pts)} pts</dd>
          <dt>Motifs de sortie</dt><dd>{fmt(rep.report.prices.exit_reason_agreement * 100, 1)} % identiques</dd>
          <dt>Net</dt><dd>réf. {fmt(rep.report.aggregate.net_ref)} · MT5 {fmt(rep.report.aggregate.net_mt5)} · écart {fmt(rep.report.aggregate.net_rel_diff * 100, 2)} %</dd>
          <dt>Coûts observés</dt><dd>commission {fmt(rep.report.costs_observed.commission_per_lot_side, 3)} / lot / côté (observée dans le testeur)</dd>
        </dl>
        <Json v={rep.report} />
      </Card>}
    </div>
  );
}
