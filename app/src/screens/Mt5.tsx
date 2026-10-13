import React, { useState } from "react";
import { api } from "../api";
import { Badge, Btn, Card, Err, Field, fmt, Json, PageHead, Table, Tile, useAction, useApi } from "../ui";
import { Explain } from "../charts";
import { useNav } from "../main";
import { costOf, DatasetCtx, RevList, RevPicker } from "./Genome";

/** Barre de concordance 0–100 % avec seuil visuel. */
function Agree({ label, v, hint, thr }: { label: string; v: number | null | undefined; hint: string; thr?: number }) {
  const p = v == null ? null : Math.max(0, Math.min(1, v));
  return (
    <div className="check" title={hint} style={{ gridTemplateColumns: "170px 1fr 70px" }}>
      <span>{label}</span>
      <div className="bar">{p != null && <i style={{ width: `${p * 100}%`, background: thr == null ? "var(--acc)" : p >= thr ? "var(--up)" : "var(--down)" }} />}
        {thr != null && <span className="thr" style={{ left: `${thr * 100}%` }} />}</div>
      <span className="val">{p == null ? "—" : `${fmt(p * 100, 1)} %`}</span>
    </div>
  );
}

export function Mt5() {
  const { nav } = useNav();
  const ea = useApi<any[]>(nav.rev ? `/genomes/${nav.rev}/ea` : null, [nav.rev], true);
  const [ctx, setCtx] = useState<any>({});
  const [p, setP] = useState({ from: "2026.08.01", to: "2026.10.01", model: 1 });
  const [rep, setRep] = useState<any>(null);
  const a = useAction();
  const R = rep?.report;
  return (
    <div>
      <PageHead title="MQL5 & parité MT5" sub="Génération de l'EA, compilation MetaEditor réelle, comparaison trade par trade avec le Strategy Tester.">
        <RevPicker />
      </PageHead>
      <div className="alert warn">Une compilation réussie ne prouve pas la parité ; une parité historique ne garantit pas la rentabilité. Le Strategy Tester en ligne de commande exige que le terminal MT5 soit fermé : sinon l'étape est signalée « bloquée ».</div>
      {nav.rev && <Card title="Générer, compiler et comparer au Strategy Tester" wide>
        <DatasetCtx value={ctx} onChange={setCtx} />
        <div className="row">
          <Field label="Du (AAAA.MM.JJ)"><input value={p.from} onChange={(e) => setP({ ...p, from: e.target.value })} /></Field>
          <Field label="Au (AAAA.MM.JJ)"><input value={p.to} onChange={(e) => setP({ ...p, to: e.target.value })} /></Field>
          <Field label="Modèle de ticks"><select value={p.model} onChange={(e) => setP({ ...p, model: Number(e.target.value) })}>
            <option value={1}>OHLC M1</option><option value={0}>Tous les ticks (générés)</option><option value={4}>Ticks réels</option></select></Field>
          <Btn kind="primary" busy={a.busy} disabled={!ctx.dataset_version_id} onClick={() => a.run(() => api.post(`/genomes/${nav.rev}/mt5-verify`, {
            dataset_version_id: ctx.dataset_version_id, context: ctx.context ?? {}, cost_profile: costOf(ctx), ...p,
          }), (x) => `Vérification soumise (tâche ${x.task_id}).`)}>Lancer la vérification</Btn>
        </div>
        {a.view}
      </Card>}
      <Err msg={ea.error} />
      {!nav.rev && <RevList />}
      <div className="grid">
        {ea.data?.map((e) => (
          <Card key={e.id} wide title={<>EA {e.id} · générateur {e.generator_version}</>}>
            <p className="muted">Source <code>{e.source_sha256.slice(0, 16)}…</code> · fuseau {e.tz_profile} · limites de risque <code>{e.risk_limits_sha256.slice(0, 12)}…</code></p>
            <h3>Compilations</h3>
            <Table rows={e.compilations} cols={[{ k: "created_at", t: "Date (UTC)" }, { k: "status", t: "Statut", f: (r) => <Badge s={r.status === "succeeded" ? "completed" : r.status === "blocked" ? "paused" : "failed"} /> },
              { k: "errors", t: "Erreurs", num: true }, { k: "warnings", t: "Avert.", num: true }, { k: "diagnostic", t: "Diagnostic" }]} />
            <h3>Parité (cliquer pour le détail)</h3>
            <Table rows={e.parity} onRow={setRep} cols={[{ k: "created_at", t: "Date (UTC)" }, { k: "status", t: "Statut" }, { k: "grade", t: "Note", f: (r) => <b>{r.grade ?? "—"}</b> },
              { k: "critical", t: "Critique", f: (r) => r.critical == null ? "—" : r.critical ? <span className="real-off">OUI</span> : "non" },
              { k: "report.trades.match_ratio", t: "Trades appariés", f: (r) => r.report ? `${fmt(r.report.trades.match_ratio * 100, 1)} %` : "—" },
              { k: "report.signals.agreement", t: "Signaux", f: (r) => r.report ? `${fmt(r.report.signals.agreement * 100, 1)} %` : "—" },
              { k: "diagnostic", t: "Diagnostic" }]} />
          </Card>))}
        {R && <>
          <div className="tiles" style={{ gridColumn: "1 / -1" }}>
            <Tile l="Note de parité" v={rep.grade ?? "—"} tone={rep.critical ? "bad" : rep.grade ? "good" : null} s={rep.critical ? "écart critique" : "aucun écart critique"} />
            <Tile l="Trades" v={`${R.trades.ref} / ${R.trades.mt5}`} s={`réf. / MT5 · ${R.trades.matched} appariés`} />
            <Tile l="Net référence" v={fmt(R.aggregate.net_ref, 0)} s="moteur QLab" />
            <Tile l="Net MT5" v={fmt(R.aggregate.net_mt5, 0)} s={`écart ${fmt(R.aggregate.net_rel_diff * 100, 2)} %`} tone={Math.abs(R.aggregate.net_rel_diff) <= 0.05 ? "good" : "bad"} />
            <Tile l="Écart entrée médian" v={`${fmt(R.prices.median_abs_entry_diff_pts)} pts`} s={`sortie ${fmt(R.prices.median_abs_exit_diff_pts)} pts`} />
          </div>
          <Card title={`Concordance moteur QLab ↔ Strategy Tester`} wide>
            {R.critical_reasons?.map((x: string, i: number) => <div key={i} className="alert err">{x}</div>)}
            <div className="checks">
              <Agree label="Signaux" v={R.signals.agreement} thr={0.95} hint="Indice de Jaccard des barres de signal : signaux communs / signaux de l'un ou l'autre moteur." />
              <Agree label="Trades appariés" v={R.trades.match_ratio} thr={0.9} hint="Trades retrouvés des deux côtés (même barre d'entrée, même sens) / plus grand des deux nombres de trades." />
              <Agree label="Motifs de sortie" v={R.prices.exit_reason_agreement} hint="Trades appariés sortis pour la même raison (stop, objectif, temps…)." />
            </div>
            <Explain>La parité vérifie que l'EA MQL5 <b>fait la même chose</b> que le moteur de recherche. Trait jaune = seuil critique (signaux 95 %, trades 90 %) : en dessous, la parité est critique. Les écarts de prix en points viennent surtout du modèle de ticks et du spread du testeur. Commission observée : {fmt(R.costs_observed?.commission_per_lot_side, 3)} / lot / côté.</Explain>
            <details style={{ marginTop: 8 }}><summary className="muted" style={{ cursor: "pointer" }}>Rapport complet (JSON)</summary><Json v={R} /></details>
          </Card>
        </>}
      </div>
    </div>
  );
}
