import React, { useState } from "react";
import { api } from "../api";
import { Btn, Card, Err, Field, fmt, Json, LineChart, Table, useAction, useApi } from "../ui";

export function Data() {
  const ds = useApi<any[]>("/datasets", [], true);
  const [sel, setSel] = useState<any>(null);
  const bars = useApi(sel ? `/datasets/${sel.id}/bars?start=-2000&limit=2000` : null, [sel?.id]);
  const imp = useAction(), syn = useAction(), st = useAction();
  const [f, setF] = useState({ symbol: "XAUUSD", tfs: "M5,H1", from: "2020-01-01", to: new Date().toISOString().slice(0, 10), tz: "NY+7" });
  const [s, setS] = useState({ n: 100000, seed: 7 });
  const [mt5, setMt5] = useState<any>(null);
  return (
    <div>
      <h1>Gestion des données & contrôle qualité</h1>
      <div className="grid">
        <Card title="Importer depuis MetaTrader 5 (lecture seule)">
          <div className="row">
            <Field label="Symbole"><input value={f.symbol} onChange={(e) => setF({ ...f, symbol: e.target.value })} /></Field>
            <Field label="Timeframes" hint="séparés par des virgules"><input value={f.tfs} onChange={(e) => setF({ ...f, tfs: e.target.value })} /></Field>
            <Field label="Du"><input type="date" value={f.from} onChange={(e) => setF({ ...f, from: e.target.value })} /></Field>
            <Field label="Au"><input type="date" value={f.to} onChange={(e) => setF({ ...f, to: e.target.value })} /></Field>
            <Field label="Fuseau serveur déclaré" hint="vérifié contre l'heure serveur observée">
              <select value={f.tz} onChange={(e) => setF({ ...f, tz: e.target.value })}><option>NY+7</option><option>UTC</option><option>UTC+2</option><option>UTC+3</option></select>
            </Field>
          </div>
          <Btn kind="primary" busy={imp.busy} onClick={() => imp.run(() => api.post("/datasets/import-mt5", {
            symbol: f.symbol, timeframes: f.tfs.split(",").map((x) => x.trim()).filter(Boolean), from: f.from, to: f.to, tz_profile: f.tz,
          }), (r) => `Import soumis (tâche ${r.task_id}).`)}>Importer</Btn>
          <Btn busy={st.busy} onClick={() => st.run(async () => { const r = await api.get("/mt5/status"); setMt5(r); return r; }, () => "Diagnostic MT5 effectué")}>Tester la connexion MT5</Btn>
          {imp.view}{st.view}
          {mt5 && <Json v={mt5} />}
        </Card>
        <Card title="Dataset synthétique de test">
          <p className="muted">Données générées, toujours étiquetées SYNTHÉTIQUES. Ne servent qu'aux tests du pipeline.</p>
          <div className="row">
            <Field label="Barres M5"><input type="number" value={s.n} onChange={(e) => setS({ ...s, n: Number(e.target.value) })} /></Field>
            <Field label="Graine"><input type="number" value={s.seed} onChange={(e) => setS({ ...s, seed: Number(e.target.value) })} /></Field>
          </div>
          <Btn busy={syn.busy} onClick={() => syn.run(() => api.post("/datasets/synthetic", s), (r) => `Génération soumise (tâche ${r.task_id}).`)}>Générer</Btn>
          {syn.view}
        </Card>
        <Card title="Versions de datasets" wide>
          <Err msg={ds.error} />
          <Table rows={ds.data} onRow={setSel} cols={[
            { k: "canonical_symbol", t: "Symbole", f: (r) => <>{r.canonical_symbol}{r.synthetic ? <span className="badge b-paused"> SYNTHÉTIQUE</span> : null}</> },
            { k: "timeframe", t: "TF" }, { k: "version", t: "v", num: true }, { k: "n_bars", t: "Barres", num: true },
            { k: "start_utc", t: "Début (UTC)" }, { k: "end_utc", t: "Fin (UTC)" }, { k: "source", t: "Source" }, { k: "broker", t: "Courtier" },
            { k: "source_timezone", t: "Fuseau" }, { k: "qc", t: "Alertes QC", f: (r) => r.qc.warnings?.length ? `${r.qc.warnings.length} ⚠` : "—" },
          ]} />
        </Card>
        {sel && <>
          <Card title={`Qualité — ${sel.canonical_symbol} ${sel.timeframe} v${sel.version}`}>
            {sel.qc.warnings?.map((w: string, i: number) => <div key={i} className="alert warn">{w}</div>)}
            <dl className="kv">
              <dt>Empreinte</dt><dd><code>{sel.content_sha256.slice(0, 24)}…</code></dd>
              <dt>Trous hors week-end</dt><dd>{JSON.stringify(sel.qc.non_weekend_gaps_by_duration)}</dd>
              <dt>Spread nul</dt><dd>{fmt(sel.qc.zero_spread_ratio * 100, 1)} %</dd>
              <dt>Volume réel</dt><dd>{sel.qc.real_volume_available ? "disponible" : "absent (tick volume seulement)"}</dd>
              <dt>Dernière barre</dt><dd>il y a {fmt(sel.qc.hours_since_last_bar, 1)} h</dd>
            </dl>
            <h3>Corrections documentées</h3>
            {sel.corrections.length ? <Json v={sel.corrections} /> : <p className="muted">Aucune.</p>}
            {sel.qc.spec_changes && <><h3>Changements de spécification</h3><Json v={sel.qc.spec_changes} /></>}
          </Card>
          <Card title="Clôtures (2 000 dernières barres)">
            <Err msg={bars.error} />
            {bars.data && <LineChart xs={(bars.data as any).ts} ys={(bars.data as any).close} unit="prix Bid" label={`${sel.canonical_symbol} ${sel.timeframe}${sel.synthetic ? " (SYNTHÉTIQUE)" : ""}`} />}
          </Card>
        </>}
      </div>
    </div>
  );
}
