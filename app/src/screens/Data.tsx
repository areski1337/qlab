import React, { useState } from "react";
import { api } from "../api";
import { Btn, Card, Err, Field, fmt, Json, PageHead, Seg, Table, Tile, useAction, useApi } from "../ui";
import { Explain, Histogram, PriceChart } from "../charts";

export function Data() {
  const ds = useApi<any[]>("/datasets", [], true);
  const [sel, setSel] = useState<any>(null);
  const [n, setN] = useState("2000");
  const bars = useApi(sel ? `/datasets/${sel.id}/bars?start=-${n}&limit=${n}` : null, [sel?.id, n]);
  const imp = useAction(), syn = useAction(), st = useAction();
  const [f, setF] = useState({ symbol: "XAUUSD", tfs: "M5,H1", from: "2020-01-01", to: new Date().toISOString().slice(0, 10), tz: "NY+7", daily: false, at: "06:00" });
  const [s, setS] = useState({ n: 100000, seed: 7 });
  const [mt5, setMt5] = useState<any>(null);
  const b = bars.data as any;
  return (
    <div>
      <PageHead title="Données & qualité" sub="Historique importé depuis MT5 (lecture seule), versions immuables, contrôle qualité visible avant toute recherche." />
      <div className="grid">
        <Card title="Versions de datasets" wide>
          <Err msg={ds.error} />
          <Table rows={ds.data} onRow={setSel} empty="Aucun dataset : importez depuis MT5 ci-dessous." cols={[
            { k: "canonical_symbol", t: "Symbole", f: (r) => <b>{r.canonical_symbol}{r.synthetic ? <span className="badge b-paused" style={{ marginLeft: 6 }}>SYNTHÉTIQUE</span> : null}</b> },
            { k: "timeframe", t: "TF" }, { k: "version", t: "v", num: true }, { k: "n_bars", t: "Barres", num: true },
            { k: "start_utc", t: "Début (UTC)" }, { k: "end_utc", t: "Fin (UTC)" }, { k: "broker", t: "Courtier" },
            { k: "source_timezone", t: "Fuseau" }, { k: "qc", t: "QC", f: (r) => r.qc.warnings?.length ? <span style={{ color: "var(--warn)" }}>{r.qc.warnings.length} alerte(s)</span> : <span style={{ color: "var(--ok)" }}>ok</span> },
          ]} />
        </Card>
        {sel && <>
          <Card title={`${sel.canonical_symbol} · ${sel.timeframe} · v${sel.version}${sel.synthetic ? " · SYNTHÉTIQUE" : ""}`} wide actions={
            <Seg label="Nombre de barres" value={n} onChange={setN} options={[["500", "500"], ["2000", "2 000"], ["5000", "5 000"], ["20000", "20 000"]]} />}>
            <Err msg={bars.error} />
            {b && <PriceChart bars={b} height={420} />}
            <Explain>Les <b>{fmt(Number(n), 0)} dernières barres</b> du dataset, temps UTC (heure d'ouverture), prix Bid. Molette : zoom · glisser : défiler · type de graphique et couleurs dans « Personnaliser ».</Explain>
          </Card>
          <div className="tiles" style={{ gridColumn: "1 / -1" }}>
            <Tile l="Barres" v={fmt(sel.n_bars, 0)} s={`${sel.start_utc?.slice(0, 10)} → ${sel.end_utc?.slice(0, 10)}`} />
            <Tile l="Spread nul" v={`${fmt(sel.qc.zero_spread_ratio * 100, 1)} %`} s="spread historique absent" tone={sel.qc.zero_spread_ratio > 0.2 ? "bad" : null}
              hint="Si élevé, fixer un spread plancher dans les coûts de campagne." />
            <Tile l="Dernière barre" v={`${fmt(sel.qc.hours_since_last_bar, 1)} h`} s="ancienneté" />
            <Tile l="Volume réel" v={sel.qc.real_volume_available ? "oui" : "non"} s={sel.qc.real_volume_available ? "disponible" : "tick volume seulement"} />
            <Tile l="Alertes QC" v={fmt(sel.qc.warnings?.length ?? 0, 0)} tone={sel.qc.warnings?.length ? "bad" : "good"} />
          </div>
          <Card title="Distribution du spread (barres affichées)">
            {b && <Histogram values={(b.spread as number[]).filter((x) => x > 0)} unit="points" marks={[]} />}
            <Explain>Hauteur = nombre de barres ayant ce spread. Une longue traîne à droite signale des moments de spread élargi (annonces, ouvertures) : les coûts réels y seront plus élevés. Barres à spread nul exclues.</Explain>
          </Card>
          <Card title="Qualité">
            {sel.qc.warnings?.map((w: string, i: number) => <div key={i} className="alert warn">{w}</div>)}
            <dl className="kv">
              <dt>Empreinte</dt><dd><code>{sel.content_sha256.slice(0, 24)}…</code></dd>
              <dt>Trous hors week-end</dt><dd>{JSON.stringify(sel.qc.non_weekend_gaps_by_duration)}</dd>
              <dt>Source</dt><dd>{sel.source}</dd>
            </dl>
            <h3>Corrections documentées</h3>
            {sel.corrections.length ? <Json v={sel.corrections} /> : <p className="muted">Aucune.</p>}
            {sel.qc.spec_changes && <><h3>Changements de spécification</h3><Json v={sel.qc.spec_changes} /></>}
          </Card>
        </>}
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
          <div className="row" style={{ alignItems: "center" }}>
            <label><input type="checkbox" checked={f.daily} onChange={(e) => setF({ ...f, daily: e.target.checked })} /> Mettre à jour chaque jour</label>
            {f.daily && <Field label="Heure (UTC)"><input type="time" value={f.at} onChange={(e) => setF({ ...f, at: e.target.value })} /></Field>}
          </div>
          <div className="actions">
            <Btn kind="primary" busy={imp.busy} onClick={() => imp.run(async () => {
              const p = { symbol: f.symbol, timeframes: f.tfs.split(",").map((x) => x.trim()).filter(Boolean), from: f.from, tz_profile: f.tz };
              const r = await api.post("/datasets/import-mt5", { ...p, to: f.to });
              if (f.daily) {
                const [hh, mm] = f.at.split(":").map(Number), t = new Date();
                t.setUTCHours(hh, mm, 0, 0);
                if (t <= new Date()) t.setUTCDate(t.getUTCDate() + 1);
                await api.post("/schedules", { name: `Mise à jour ${p.symbol} ${p.timeframes.join("/")}`, kind: "import_mt5", payload: p, every: "daily", first_run_utc: t.toISOString() });
              }
              return r;
            }, (r) => `Import soumis (tâche ${r.task_id})${f.daily ? " ; mise à jour quotidienne programmée" : ""}.`)}>Importer</Btn>
            <Btn busy={st.busy} onClick={() => st.run(async () => { const r = await api.get("/mt5/status"); setMt5(r); return r; }, () => "Diagnostic MT5 effectué")}>Tester la connexion MT5</Btn>
          </div>
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
      </div>
    </div>
  );
}
