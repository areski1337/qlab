import React, { useEffect, useMemo, useState } from "react";
import { api } from "../api";
import { Badge, Btn, Card, Err, Field, fmt, Json, PageHead, Seg, signTone, STATUS_FR, Table, Tile, useAction, useApi, utc } from "../ui";
import { Bars, EquityChart, Explain, Heatmap, Histogram, PriceChart, Ranges, Stack, Trade } from "../charts";
import { useNav } from "../main";
import { LADDER } from "./Dashboard";
import { PerfReport } from "../report";
import { EMPTY_GENOME, GenomeEditor, renumber } from "../editor";

/** Création / modification de stratégie : éditeur visuel ou JSON, même brouillon. */
function StrategyEditor({ current }: { current: any }) {
  const { nav, go } = useNav();
  const [mode, setMode] = useState<"visual" | "json">("visual");
  const [g, setG] = useState<any>(EMPTY_GENOME);
  const [txt, setTxt] = useState(JSON.stringify(EMPTY_GENOME, null, 2));
  const [jsonErr, setJsonErr] = useState<string | null>(null);
  const c = useAction();
  const load = (x: any) => { setG(x); setTxt(JSON.stringify(x, null, 2)); setJsonErr(null); };
  const switchMode = (m: "visual" | "json") => {
    if (m === "visual") { try { setG(JSON.parse(txt)); } catch (e: any) { setJsonErr(`JSON invalide : ${e.message}`); return; } }
    else setTxt(JSON.stringify(renumber(g), null, 2));
    setJsonErr(null); setMode(m);
  };
  return (
    <Card title="Créer ou modifier une stratégie" wide actions={<>
      <Seg label="Mode" value={mode} onChange={switchMode} options={[["visual", "Visuel"], ["json", "JSON"]]} />
      {current && <button className="btn" onClick={() => load(current.content)}>Partir de la révision ouverte</button>}
      <button className="btn" onClick={() => load(EMPTY_GENOME)}>Nouvelle stratégie</button>
    </>}>
      {mode === "visual" ? <GenomeEditor g={g} onChange={setG} />
        : <textarea rows={16} style={{ width: "100%" }} value={txt} onChange={(e) => setTxt(e.target.value)} aria-label="Génome JSON" />}
      <Err msg={jsonErr} />
      <div className="actions" style={{ marginTop: 10 }}>
        <Btn kind="primary" busy={c.busy} onClick={() => c.run(async () => {
          const genome = mode === "visual" ? renumber(g) : JSON.parse(txt);
          const x = await api.post("/genomes", { genome }); go({ ...nav, rev: x.id }); return x;
        }, (x) => `Révision ${x.id} créée (immuable) : lancer un backtest ou la validation.`)}>Créer la révision</Btn>
        <span className="muted">Une révision est immuable : enregistrer une modification crée une nouvelle stratégie, l'originale reste intacte.</span>
      </div>
      {c.view}
    </Card>
  );
}

export function RevPicker() {
  const { nav, go } = useNav();
  const [v, setV] = useState(nav.rev ?? "");
  const recent = useApi<any[]>("/genomes?limit=200");
  useEffect(() => setV(nav.rev ?? ""), [nav.rev]);
  return (
    <div className="row" style={{ alignItems: "center" }}>
      <input aria-label="Révision de génome" list="qlab-revs" style={{ width: 300 }} value={v} onChange={(e) => setV(e.target.value)}
        onKeyDown={(e) => e.key === "Enter" && go({ ...nav, rev: v.trim() })} placeholder="rev_… (Entrée pour ouvrir)" />
      <datalist id="qlab-revs">{recent.data?.map((r) => <option key={r.id} value={r.id}>{STATUS_FR[r.status] ?? r.status}</option>)}</datalist>
      <button className="btn" onClick={() => go({ ...nav, rev: v.trim() })}>Ouvrir</button>
    </div>
  );
}

/** Sans révision ouverte : les plus avancées dans la validation d'abord. */
export function RevList() {
  const { nav, go } = useNav();
  const g = useApi<any[]>("/genomes?limit=500", [], true);
  const rank = (s: string) => (s === "rejected" || s === "quarantined" ? -1 : LADDER.indexOf(s));
  const rows = g.data?.slice().sort((a, b) => rank(b.status) - rank(a.status)).slice(0, 40) ?? null;
  return (
    <Card title="Choisir une révision" wide>
      <Table rows={rows} onRow={(r) => go({ ...nav, rev: r.id })} empty="Aucune révision : lancer une campagne ou créer un génome." cols={[
        { k: "id", t: "Révision", f: (r) => <b>{r.id}</b> }, { k: "status", t: "Statut", f: (r) => <Badge s={r.status} /> },
        { k: "campaign_id", t: "Campagne" }, { k: "created_at", t: "Créée (UTC)" }]} />
    </Card>
  );
}

/** Marché et hypothèses de coûts d'une évaluation. `fromCampaign` : préremplit dataset, contexte et coûts avec ceux de la
 * campagne d'origine, pour valider une stratégie dans les conditions où elle a été trouvée. */
export function DatasetCtx({ value, onChange, fromCampaign }: { value: any; onChange: (v: any) => void; fromCampaign?: string | null }) {
  const ds = useApi<any[]>("/datasets");
  const base = ds.data?.find((d) => d.id === value.dataset_version_id);
  useEffect(() => {
    if (!fromCampaign || value.dataset_version_id) return;
    api.get(`/campaigns/${fromCampaign}`).then((c: any) => {
      const k = c.config, cp = k.cost_profile ?? {};
      onChange({ dataset_version_id: k.dataset_version_id, context: Object.fromEntries(Object.entries(k.context_version_ids ?? {})),
        mode: cp.spread_mode ?? "max", spread: cp.fixed_spread_points ?? "", commission: cp.commission_per_lot_side ?? 0,
        slippage: cp.slippage_points ?? 0, swap: cp.apply_swap ?? true, baseCost: cp, from: c.name });
    }).catch(() => undefined);
  }, [fromCampaign]);
  const set = (k: string, v: any) => onChange({ ...value, [k]: v });
  const zero = (base?.qc?.zero_spread_ratio ?? 0) > 0;
  const needSpread = (value.mode ?? "max") === "fixed" || (zero && (value.mode ?? "max") !== "bars");
  return (
    <>
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
      </div>
      <div className="row">
        <Field label="Spread" hint={zero ? `spread historique nul sur ${fmt(base.qc.zero_spread_ratio * 100, 1)} % des barres` : undefined}>
          <select value={value.mode ?? "max"} onChange={(e) => set("mode", e.target.value)}>
            <option value="max">max(historique, plancher)</option><option value="bars">historique seul</option><option value="fixed">fixe</option>
          </select></Field>
        <Field label={(value.mode ?? "max") === "fixed" ? "Spread fixe (points)" : "Plancher (points)"}>
          <input type="number" min={0} value={value.spread ?? ""} onChange={(e) => set("spread", e.target.value)} aria-invalid={needSpread && value.spread === ""} /></Field>
        <Field label="Commission / lot / côté"><input type="number" min={0} step="0.01" value={value.commission ?? 0} onChange={(e) => set("commission", Number(e.target.value))} /></Field>
        <Field label="Glissement (points / exécution)"><input type="number" min={0} value={value.slippage ?? 0} onChange={(e) => set("slippage", Number(e.target.value))} /></Field>
        <label><input type="checkbox" checked={value.swap ?? true} onChange={(e) => set("swap", e.target.checked)} /> swap (spécification du symbole)</label>
      </div>
      {value.from && <p className="muted">Conditions reprises de la campagne « {value.from} ».</p>}
      {needSpread && (value.spread === "" || value.spread == null) && <div className="alert warn">Spread requis : les données n'en fournissent pas sur toutes les barres (l'évaluation serait refusée).</div>}
    </>
  );
}

/** Profil de coûts envoyé au moteur ; provenance « assumed » pour toute valeur saisie (jamais présentée comme observée). */
export const costOf = (v: any) => ({
  ...(v.baseCost ?? {}), name: v.baseCost?.name ?? "ui", version: v.baseCost?.version ?? 1,
  spread_mode: v.mode ?? "max", fixed_spread_points: v.spread === "" || v.spread == null ? null : Number(v.spread),
  commission_per_lot_side: v.commission ?? 0, slippage_points: v.slippage ?? 0, apply_swap: v.swap ?? true,
  provenance: {
    // une valeur modifiée par rapport à la campagne perd sa provenance d'origine : elle devient une hypothèse
    spread: same(v, "fixed_spread_points", v.spread === "" || v.spread == null ? null : Number(v.spread)) && same(v, "spread_mode", v.mode ?? "max") ? v.baseCost.provenance?.spread ?? "assumed" : "assumed",
    commission: same(v, "commission_per_lot_side", v.commission ?? 0) ? v.baseCost.provenance?.commission ?? "assumed" : "assumed",
    slippage: same(v, "slippage_points", v.slippage ?? 0) ? v.baseCost.provenance?.slippage ?? "assumed" : "assumed", swap: "symbol_spec" },
});
const same = (v: any, k: string, x: any) => !!v.baseCost && v.baseCost[k] === x;

/** Échelle de validation : étapes franchies, étape courante, rejet. */
function Ladder({ status, transitions }: { status: string; transitions: any[] }) {
  const reached = new Set(transitions.map((t) => t.to_status));
  const rejected = status === "rejected" || status === "quarantined";
  const lastOk = LADDER.filter((k) => reached.has(k) || k === status).map((k) => LADDER.indexOf(k));
  const cur = rejected ? Math.max(0, ...lastOk) : LADDER.indexOf(status);
  return (
    <div className="ladder" role="list" aria-label="Échelle de validation">
      {LADDER.map((k, i) => {
        const cls = i < cur || (i === cur && !rejected && i === LADDER.length - 1) ? "done" : i === cur ? (rejected ? "done" : "cur") : rejected && i === cur + 1 ? "fail" : "";
        const tr = transitions.find((t) => t.to_status === k);
        return <div key={k} role="listitem" className={"st " + cls}><b>{STATUS_FR[k]}</b>
          <span className="n">{rejected && i === cur + 1 ? "échec — preuve conservée" : tr ? tr.ts.slice(0, 10) : i <= cur ? "" : "à venir"}</span></div>;
      })}
    </div>
  );
}

export function GenomeExplorer() {
  const { nav, go } = useNav();
  const r = useApi(nav.rev ? `/genomes/${nav.rev}` : null, [nav.rev], true);
  const [ctx, setCtx] = useState<any>({});
  const adv = useAction();
  const d = r.data;
  const rob = d?.transitions?.slice().reverse().find((t: any) => t.evidence?.robustness_report)?.evidence.robustness_report;
  const ev = (seg: string) => d?.evaluations?.filter((e: any) => e.segment === seg).at(-1)?.metrics;
  const research = ev("research") ?? ev("train");
  return (
    <div>
      <PageHead title="Génome & validation" sub="Règles en clair, généalogie, et preuves de chaque étape de validation.">
        <RevPicker />
      </PageHead>
      <Err msg={r.error} />
      {!nav.rev && <RevList />}
      {d && <>
        <Card title={<>{d.id} <Badge s={d.status} /></>} wide actions={<>
          <button className="btn" onClick={() => go({ ...nav, screen: "backtests" })}>Backtest</button>
          <button className="btn" onClick={() => go({ ...nav, screen: "passport" })}>Passeport</button>
          <button className="btn" onClick={() => go({ ...nav, screen: "mt5" })}>MQL5</button>
        </>}>
          <Ladder status={d.status} transitions={d.transitions} />
          {d.status === "rejected" && <div className="alert err">Rejetée : {d.transitions.at(-1)?.criteria?.reason ?? "voir l'historique"}</div>}
          {d.export_blockers.length > 0 && <div className="alert warn">Export MQL5 bloqué : {d.export_blockers.join(" ; ")}</div>}
        </Card>
        {research && <div className="tiles">
          <Tile l="Sharpe" v={fmt(research.sharpe, 2)} tone={signTone(research.sharpe)} s="dernière évaluation de recherche" />
          <Tile l="Profit net" v={fmt(research.net_profit, 0)} tone={signTone(research.net_profit)} s={`${fmt(research.return_pct, 1)} %`} />
          <Tile l="Drawdown max" v={`${fmt(research.max_dd_pct, 1)} %`} s="pire baisse depuis un sommet" />
          <Tile l="Trades" v={fmt(research.n_trades, 0)} s={`réussite ${fmt(research.win_rate * 100, 0)} %`} />
          <Tile l="Profit factor" v={fmt(research.profit_factor, 2)} tone={research.profit_factor == null ? null : research.profit_factor >= 1 ? "good" : "bad"} s="gains bruts / pertes brutes" />
          <Tile l="Espérance" v={`${fmt(research.expectancy_r, 2)} R`} tone={signTone(research.expectancy_r)} s="gain moyen par trade, en risques" />
        </div>}
        <div className="grid">
          <Card title="Règles de la stratégie">
            <dl className="kv rules">{Object.entries(d.description).map(([k, v]) => <React.Fragment key={k}><dt>{k}</dt><dd>{String(v)}</dd></React.Fragment>)}</dl>
            <p className="muted">Génome {d.genome_id} · révision {d.revision} · empreinte <code>{d.semantic_hash.slice(0, 16)}…</code></p>
          </Card>
          <Card title="Généalogie (ascendants)">
            <Table rows={d.lineage} empty="Racine : aucun parent (génération initiale ou création manuelle)." onRow={(x) => go({ ...nav, rev: x.parent_id })} cols={[
              { k: "child_id", t: "Enfant" }, { k: "parent_id", t: "Parent" }, { k: "operator", t: "Opérateur" }, { k: "operator_version", t: "v" }]} />
          </Card>
          {rob && <Robustness sha={rob} />}
          <Card title="Faire progresser la validation" wide>
            <p className="muted">Filtrage → historique → robustesse → hors échantillon. Chaque étape exige des preuves ; un échec rejette la révision (preuve conservée).</p>
            <DatasetCtx value={ctx} onChange={setCtx} fromCampaign={d.campaign_id} />
            <Btn kind="primary" busy={adv.busy} disabled={!ctx.dataset_version_id} onClick={() => adv.run(() => api.post(`/genomes/${d.id}/advance`, {
              dataset_version_id: ctx.dataset_version_id, context: ctx.context ?? {}, cost_profile: costOf(ctx), campaign_id: d.campaign_id,
            }), (x) => `Validation soumise (tâche ${x.task_id}).`)}>Lancer la validation</Btn>
            {adv.view}
            <h3>Historique des statuts</h3>
            <Table rows={d.transitions} empty="Aucune transition." cols={[{ k: "ts", t: "Date (UTC)" }, { k: "from_status", t: "De" },
              { k: "to_status", t: "Vers", f: (x) => <Badge s={x.to_status} /> }, { k: "criteria", t: "Critères", f: (x) => JSON.stringify(x.criteria).slice(0, 90) },
              { k: "evidence", t: "Preuves", f: (x) => Object.keys(x.evidence).join(", ") }]} />
          </Card>
          <Card title="Génome canonique (JSON)" wide><details><summary className="muted" style={{ cursor: "pointer" }}>Afficher le JSON</summary><Json v={d.content} /></details></Card>
        </div>
      </>}
      <div className="grid">
        <StrategyEditor current={d} />
      </div>
    </div>
  );
}

// ---------------------------------------------------------------- rapport de robustesse
const CHECKS: Record<string, { label: string; thr: (c: any) => number; higher: boolean; unit: string; why: string; pct?: boolean }> = {
  min_trades: { label: "Nombre de trades", thr: (c) => c.min_trades, higher: true, unit: "trades", why: "Assez d'occasions pour que les statistiques aient un sens." },
  walk_forward: { label: "Walk-forward", thr: (c) => c.wf_positive_folds_ratio, higher: true, unit: "plis positifs", pct: true, why: "Mêmes règles sur des périodes successives : part des périodes gagnantes." },
  walk_forward_reopt: { label: "Walk-forward ré-optimisé", thr: (c) => c.wfo_positive_folds_ratio, higher: true, unit: "plis positifs", pct: true, why: "Paramètres ré-ajustés sur le passé puis testés sur la suite : la méthode tient-elle ?" },
  sensitivity: { label: "Sensibilité", thr: (c) => c.sensitivity_positive_ratio, higher: true, unit: "voisins positifs", pct: true, why: "Petites variations des paramètres : une bonne stratégie ne s'effondre pas." },
  "cost_stress_x1.5": { label: "Coûts ×1,5", thr: () => 0, higher: true, unit: "espérance", why: "Reste-t-elle gagnante si le spread réel est multiplié par 1,5 ?" },
  mc_p95_max_dd: { label: "Drawdown Monte Carlo p95", thr: (c) => c.mc_p95_max_dd_pct, higher: false, unit: "%", why: "Pire drawdown plausible (95 %) en rebattant l'ordre des trades." },
  random_baseline: { label: "Contre le hasard", thr: (c) => c.random_baseline_p_max, higher: false, unit: "p-valeur", why: "Probabilité que des entrées aléatoires fassent aussi bien. Basse = bon." },
  deflated_sharpe: { label: "Sharpe dégonflé (DSR)", thr: (c) => c.dsr_min, higher: true, unit: "probabilité", why: "Sharpe (fenêtre train) corrigé du nombre de stratégies essayées sur cette série, toutes campagnes confondues (biais de sélection)." },
};

function CheckRow({ k, c, crit }: { k: string; c: { value: number | null; pass: boolean | null }; crit: any }) {
  const m = CHECKS[k] ?? { label: k, thr: () => 0, higher: true, unit: "", why: "" };
  const thr = m.thr(crit);
  const v = c.value;
  const max = m.pct || m.unit === "probabilité" || m.unit === "p-valeur" ? 1 : Math.max(Math.abs(v ?? 0), Math.abs(thr), 1e-9) * 1.25;
  const pos = (x: number) => `${Math.max(0, Math.min(100, (x / max) * 100))}%`;
  const show = (x: number | null) => x == null ? "—" : m.pct ? `${fmt(x * 100, 0)} %` : fmt(x, m.unit === "trades" ? 0 : 3);
  return (
    <div className="check" title={m.why}>
      <span className={"ico " + (c.pass == null ? "na" : c.pass ? "ok" : "ko")}>{c.pass == null ? "?" : c.pass ? "✓" : "✕"}</span>
      <span>{m.label}</span>
      <div className="bar">
        {v != null && <i style={{ width: pos(v), background: c.pass ? "var(--up)" : c.pass === false ? "var(--down)" : "var(--mut)" }} />}
        <span className="thr" style={{ left: pos(thr) }} />
      </div>
      <span className="val">{show(v)} <span className="muted">{m.higher ? "≥" : "≤"} {show(thr)}</span></span>
    </div>
  );
}

function Robustness({ sha }: { sha: string }) {
  const r = useApi<any>(`/artifacts/${sha}`, [sha]);
  const rep = r.data;
  if (r.error) return <Card title="Rapport de robustesse" wide><Err msg={r.error} /></Card>;
  if (!rep) return <Card title="Rapport de robustesse" wide><p className="muted">Chargement…</p></Card>;
  const crit = rep.criteria ?? {};
  const mc = rep.monte_carlo, rb = rep.random_baseline, ds = rep.deflated_sharpe, wfo = rep.walk_forward_reopt;
  const cs = rep.cost_stress ?? {};
  const sens = (rep.sensitivity?.neighbors ?? []).slice().sort((a: any, b: any) => (b.expectancy ?? -1e9) - (a.expectancy ?? -1e9));
  return (
    <>
      <Card title={<>Rapport de robustesse {rep.passed ? <Badge s="completed" /> : <Badge s="rejected" />}</>} wide>
        <div className="checks">{Object.entries(rep.checks).map(([k, c]: any) => <CheckRow key={k} k={k} c={c} crit={crit} />)}</div>
        <Explain>Chaque ligne = un test de stress. La barre montre la valeur obtenue ; le <b>trait jaune</b> est le seuil exigé. Il faut <b>tous</b> les tests au vert pour passer « robustesse testée ». Les tests sont exécutés du moins coûteux au plus coûteux : après un premier échec, les suivants ne sont pas lancés (« ? »). Survoler une ligne explique le test.</Explain>
      </Card>
      <Card title="Walk-forward : profit par période de test">
        <Bars unit="profit net" items={(rep.walk_forward?.folds ?? []).map((f: any) => ({ label: `pli ${f.fold}`, value: f.net_profit, tip: `${f.n_trades} trades · Sharpe ${fmt(f.sharpe)} · PF ${fmt(f.profit_factor)}` }))} />
        <Explain>La période de recherche est découpée en tranches successives, testées avec <b>les mêmes règles</b>. Des barres majoritairement vertes = l'avantage n'est pas concentré sur une seule période chanceuse. <b>Test in-sample</b> : ces périodes ont servi à découvrir la stratégie ; ce n'est pas une preuve hors échantillon.</Explain>
      </Card>
      <Card title={`Walk-forward ré-optimisé · WFE ${wfo?.wfe == null ? "—" : fmt(wfo.wfe, 2)}`}>
        <Bars unit="Sharpe" items={(wfo?.folds ?? []).flatMap((f: any) => [
          { label: `p${f.fold} appr.`, value: f.fit_sharpe, muted: true, tip: "Sharpe sur la fenêtre d'apprentissage (jeu retenu)" },
          { label: `p${f.fold} test`, value: f.sharpe, tip: `${f.n_trades} trades · net ${fmt(f.net_profit)}${f.chosen_is_original ? "\nparamètres d'origine conservés" : "\nparamètres ré-ajustés"}` },
        ])} />
        <Explain>Gris = performance sur la période d'apprentissage ; couleur = sur la période suivante, non utilisée pour ré-ajuster les paramètres (mais incluse dans la recherche de la structure : test in-sample). <b>WFE</b> = test / apprentissage : proche de 1 = ce qui est appris se transfère ; proche de 0 ou négatif = surapprentissage.</Explain>
      </Card>
      {mc?.available && <Card title="Monte Carlo (1 000 tirages)">
        <Ranges rows={[
          { label: "Profit net", p5: mc.bootstrap_net.p5, p50: mc.bootstrap_net.p50, p95: mc.bootstrap_net.p95, actual: rep.base?.net_profit, thr: 0, unit: "devise du compte" },
          { label: "Drawdown max", p5: mc.bootstrap_max_dd_pct.p5, p50: mc.bootstrap_max_dd_pct.p50, p95: mc.bootstrap_max_dd_pct.p95, thr: crit.mc_p95_max_dd_pct, unit: "%" },
          { label: "DD (ordre permuté)", p5: mc.permutation_max_dd_pct.p5, p50: mc.permutation_max_dd_pct.p50, p95: mc.permutation_max_dd_pct.p95, thr: crit.mc_p95_max_dd_pct, unit: "%" },
        ]} />
        <Explain always>Les trades sont rejoués dans un ordre aléatoire (avec remise) 1 000 fois. La bande va du 5<sup>e</sup> au 95<sup>e</sup> centile, le trait = médiane, le point = résultat réel. Probabilité de finir en perte : <b>{fmt(mc.prob_net_negative * 100, 1)} %</b>. Hypothèse : trades indépendants.</Explain>
      </Card>}
      {rb?.available && <Card title="Contre des entrées aléatoires">
        <Ranges rows={[{ label: "Espérance / trade", p5: rb.random_expectancy_p50, p50: rb.random_expectancy_p50, p95: rb.random_expectancy_p95, actual: rb.strategy_expectancy, unit: "devise / trade" }]} />
        <Explain>{rb.n} stratégies avec <b>entrées au hasard</b> mais mêmes sorties et même risque. Bande = hasard (médiane → 95<sup>e</sup> centile) ; point = la stratégie. p-valeur <b>{fmt(rb.p_value, 3)}</b> : part des tirages aléatoires faisant au moins aussi bien.</Explain>
      </Card>}
      <Card title="Sensibilité aux paramètres">
        <Bars unit="espérance / trade" items={sens.map((n: any) => ({ label: "", value: n.expectancy, tip: `${n.variant}\n${n.n_trades} trades · net ${fmt(n.net_profit)}` }))} />
        <Explain>Chaque barre = une variante voisine (paramètre ±10–20 %), triées de la meilleure à la pire. Un mur vert = <b>plateau stable</b> ; beaucoup de rouge = pic fragile, probablement du sur-ajustement.</Explain>
      </Card>
      <Card title="Stress de coûts">
        <Bars unit="espérance / trade" items={[{ label: "base", value: rep.base?.expectancy, tip: "coûts de la campagne" },
          ...Object.entries(cs).filter(([k, v]) => !k.startsWith("_") && typeof v === "object").map(([k, v]: any) => ({ label: k, value: v.expectancy, tip: `${v.n_trades} trades · net ${fmt(v.net_profit)}` }))]} />
        <Explain>Même stratégie avec des coûts dégradés (spread ×1,5 / ×2, glissement, commission). Si l'espérance passe sous zéro dès ×1,5, l'avantage est trop mince pour le réel. {cs._note}</Explain>
      </Card>
      {ds?.available && <div className="tiles" style={{ gridColumn: "1 / -1" }}>
        <Tile l="Sharpe dégonflé" v={fmt(ds.dsr, 3)} tone={ds.dsr >= (crit.dsr_min ?? 0.9) ? "good" : "bad"} s={`seuil ${fmt(crit.dsr_min, 2)} · ${ds.n_trials} essais sur la série`}
          hint="Probabilité que le vrai Sharpe soit positif, compte tenu du nombre de stratégies essayées." />
        <Tile l="Sharpe journalier" v={fmt(ds.sr_daily, 4)} s={`vs ${fmt(ds.sr0_daily, 4)} attendu par chance`} />
        <Tile l="Asymétrie" v={fmt(ds.skew, 2)} s="négative = pertes rares mais fortes" />
        <Tile l="Kurtosis" v={fmt(ds.kurtosis, 2)} s="> 3 = queues épaisses" />
      </div>}
      {Object.keys(rep.transfer ?? {}).length > 0 && <Card title="Transfert vers d'autres instruments" wide>
        <Table rows={Object.entries(rep.transfer).map(([s, v]: any) => ({ id: s, s, ...v }))} cols={[{ k: "s", t: "Instrument" },
          { k: "n_trades", t: "Trades", num: true }, { k: "net_profit", t: "Net", num: true, tone: true }, { k: "sharpe", t: "Sharpe", num: true, tone: true },
          { k: "profit_factor", t: "PF", num: true }, { k: "max_dd_pct", t: "DD %", num: true }, { k: "error", t: "Erreur" }]} />
        <Explain always>Informatif : les mêmes règles appliquées tel quel à d'autres marchés. Un transfert positif renforce la confiance ; son absence n'invalide pas une stratégie spécialisée.</Explain>
      </Card>}
    </>
  );
}

export function Passport() {
  const { nav } = useNav();
  const [html, setHtml] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const ex = useAction();
  useEffect(() => {
    setHtml(null); setErr(null);
    if (!nav.rev) return;
    window.qlab.request("GET", `/api/v1/genomes/${nav.rev}/passport.html`).then((r) => r.status === 200 ? setHtml(r.data) : setErr(JSON.stringify(r.data)));
  }, [nav.rev]);
  return (
    <div>
      <PageHead title="Passeport de stratégie" sub="Document de synthèse exportable : règles, preuves, limites.">
        <RevPicker />
        {nav.rev && <Btn busy={ex.busy} onClick={() => ex.run(() => api.post(`/genomes/${nav.rev}/export`), (r) => `Export soumis (tâche ${r.task_id}) ; l'archive apparaîtra dans le répertoire exports.`)}>Exporter (génome, passeport, EA, manifeste)</Btn>}
      </PageHead>
      <Err msg={err} />
      {!nav.rev && <RevList />}
      {ex.view}
      {html && <iframe className="passport" title="Passeport" sandbox="" srcDoc={html} />}
    </div>
  );
}

// ---------------------------------------------------------------- backtests
const DOW = ["lun", "mar", "mer", "jeu", "ven", "sam", "dim"];

export function Backtests() {
  const { nav } = useNav();
  const [ctx, setCtx] = useState<any>({});
  const [seg, setSeg] = useState("research");
  const r = useApi(nav.rev ? `/genomes/${nav.rev}` : null, [nav.rev], true);
  const [evalSel, setEvalSel] = useState<any>(null);
  const [view, setView] = useState<"equity" | "price">("equity");
  const trades = useApi(evalSel?.trades_artifact ? `/artifacts/${evalSel.trades_artifact}` : null, [evalSel?.id]);
  const a = useAction();
  const tr: Trade[] = (trades.data as any)?.trades ?? [];
  const w = evalSel?.window as [number, number] | undefined;
  const span = w ? Math.min(20000, w[1] - w[0]) : 0;
  const bars = useApi(view === "price" && evalSel && w ? `/datasets/${evalSel.dataset_version_id}/bars?start=${w[1] - span}&limit=${span}` : null, [evalSel?.id, view]);
  const evs: any[] = (r.data as any)?.evaluations ?? [];
  useEffect(() => { setEvalSel(evs.filter((e) => e.trades_artifact).at(-1) ?? evs.at(-1) ?? null); }, [nav.rev, evs.length]);
  const m = evalSel?.metrics;
  const stats = useMemo(() => {
    const hour: (number | null)[][] = DOW.slice(0, 5).map(() => Array(24).fill(null));
    const month = new Map<string, number>();
    const reasons = new Map<string, number>();
    for (const t of tr) {
      const d = new Date(t.entry_ts * 1000);
      const dw = (d.getUTCDay() + 6) % 7;
      if (dw < 5) hour[dw][d.getUTCHours()] = (hour[dw][d.getUTCHours()] ?? 0) + t.pnl;
      const mk = new Date(t.exit_ts * 1000).toISOString().slice(0, 7);
      month.set(mk, (month.get(mk) ?? 0) + t.pnl);
      reasons.set(t.reason ?? "?", (reasons.get(t.reason ?? "?") ?? 0) + 1);
    }
    let s = 0;
    const cum = tr.slice().sort((x, y) => x.exit_ts - y.exit_ts).map((t) => (s += t.pnl));
    return { hour, month: [...month.entries()].sort(), reasons: [...reasons.entries()], cum };
  }, [tr]);
  return (
    <div>
      <PageHead title="Backtests & transactions" sub="Moteur de référence, après coûts. Choisir une évaluation pour l'analyser.">
        <RevPicker />
      </PageHead>
      <Err msg={r.error} />
      {!nav.rev && <RevList />}
      {r.data && <Card title="Évaluations de cette révision" wide>
        <Table rows={evs.slice().reverse()} onRow={setEvalSel} empty="Aucune évaluation : lancer un backtest ci-dessous." cols={[
          { k: "segment", t: "Segment", f: (x) => <b style={{ color: x.id === evalSel?.id ? "var(--acc)" : undefined }}>{x.segment}</b> },
          { k: "metrics.n_trades", t: "Trades", num: true }, { k: "metrics.net_profit", t: "Net", num: true, tone: true },
          { k: "metrics.profit_factor", t: "PF", num: true }, { k: "metrics.sharpe", t: "Sharpe", num: true, tone: true }, { k: "metrics.max_dd_pct", t: "DD %", num: true },
          { k: "metrics.expectancy_r", t: "Esp. R", num: true, tone: true }, { k: "trades_artifact", t: "Trades", f: (x) => x.trades_artifact ? "conservés" : "—" },
          { k: "created_at", t: "Date (UTC)" }]} />
      </Card>}
      {m && <div className="tiles">
        <Tile l="Profit net" v={fmt(m.net_profit, 0)} tone={signTone(m.net_profit)} s={`${fmt(m.return_pct, 1)} % · segment ${evalSel.segment}`} spark={tr.length ? stats.cum : undefined} />
        <Tile l="Sharpe" v={fmt(m.sharpe, 2)} tone={signTone(m.sharpe)} s="rendement / volatilité" />
        <Tile l="Drawdown max" v={`${fmt(m.max_dd_pct, 1)} %`} s="pire baisse depuis un sommet" />
        <Tile l="Profit factor" v={fmt(m.profit_factor, 2)} tone={m.profit_factor == null ? null : m.profit_factor >= 1 ? "good" : "bad"} s="gains / pertes bruts" />
        <Tile l="Réussite" v={`${fmt(m.win_rate * 100, 0)} %`} s={`${fmt(m.n_trades, 0)} trades`} />
        <Tile l="Espérance" v={`${fmt(m.expectancy_r, 2)} R`} tone={signTone(m.expectancy_r)} s="par trade, en unités de risque" />
      </div>}
      {evalSel && <div className="grid">
        <Card title={view === "equity" ? "Courbe de capital & drawdown" : "Prix & transactions"} wide actions={
          <Seg label="Vue" value={view} onChange={setView} options={[["equity", "Capital"], ["price", "Prix + trades"]]} />}>
          {trades.error && <Err msg={trades.error} />}
          {!evalSel.trades_artifact ? <p className="muted">Transactions non conservées pour cette évaluation (relancer avec conservation).</p>
            : view === "equity" ? <>
              <EquityChart trades={tr} initial={m?.initial_equity ?? 10000} height={380} />
              <Explain always>Capital de clôture par trade (référence : capital initial) ; volet inférieur : drawdown en % du dernier sommet. Courbe par trade, pas mark-to-market : la perte latente intra-trade n'apparaît pas.</Explain>
            </> : <>
              <Err msg={bars.error} />
              {bars.data && <PriceChart bars={bars.data as any} trades={tr} height={420} />}
              <Explain always>Flèches = entrées (▲ long, ▼ short) ; ronds = sorties, annotées du résultat en R (multiple du risque initial). {span < (w ? w[1] - w[0] : 0) ? `Seules les ${fmt(span, 0)} dernières barres de la période sont affichées.` : ""}</Explain>
            </>}
        </Card>
        <PerfReport ev={evalSel} trades={tr} />
        {tr.length > 0 && <>
          <Card title="Distribution des résultats (R)">
            <Histogram values={tr.map((t) => t.r ?? NaN)} unit="R" marks={[{ v: 0, label: "0" }, { v: m?.expectancy_r ?? NaN, label: "moyenne" }]} />
            <Explain>Chaque barre compte les trades d'un résultat donné, en multiples du risque (−1 R = stop touché). Une bonne stratégie a souvent <b>beaucoup de petites pertes et quelques gros gains</b> à droite.</Explain>
          </Card>
          <Card title="Profit par mois">
            <Bars unit="profit net" items={stats.month.map(([k, v]) => ({ label: k.slice(2), value: v }))} />
            <Explain>Régularité dans le temps : des gains répartis sur de nombreux mois valent mieux qu'un seul mois exceptionnel.</Explain>
          </Card>
          <Card title="Profit selon l'heure d'entrée (UTC)" wide>
            <Heatmap rows={DOW.slice(0, 5)} cols={Array.from({ length: 24 }, (_, i) => String(i))} get={(r, c) => stats.hour[r][c]} unit="profit net" fmtv={(v) => fmt(v, 0)} />
            <Explain>Case = somme des résultats des trades ouverts ce jour-là à cette heure. Vert = rentable, rouge = perdant, gris = aucun trade. Utile pour repérer une session qui porte (ou plombe) la stratégie.</Explain>
          </Card>
          <Card title="Motifs de sortie">
            <Stack unit="trades" parts={stats.reasons.map(([k, v]) => ({ label: k, value: v }))} />
            <Explain>Comment les trades se terminent : objectif atteint, stop, sortie temporelle, clôture de fin de journée ou de week-end…</Explain>
          </Card>
          <Card title={`${tr.length} transactions`} wide>
            <Table rows={tr.map((t, i) => ({ id: i, ...t }))} cols={[
              { k: "entry_ts", t: "Entrée (UTC)", f: (t) => utc(t.entry_ts) }, { k: "dir", t: "Sens", f: (t) => t.dir === 1 ? <span style={{ color: "var(--up)" }}>▲ long</span> : <span style={{ color: "var(--down)" }}>▼ short</span> },
              { k: "lots", t: "Lots", num: true }, { k: "entry", t: "Prix entrée", num: true, f: (t) => fmt(t.entry, 5) }, { k: "exit", t: "Prix sortie", num: true, f: (t) => fmt(t.exit, 5) },
              { k: "reason", t: "Motif" }, { k: "ambiguous", t: "Ambigu", f: (t) => t.ambiguous ? "oui" : "" }, { k: "r", t: "R", num: true, tone: true },
              { k: "commission", t: "Comm.", num: true }, { k: "swap", t: "Swap", num: true }, { k: "pnl", t: "PnL net", num: true, tone: true }, { k: "bars_held", t: "Barres", num: true }]} />
          </Card>
        </>}
      </div>}
      {nav.rev && <div className="grid"><Card title="Lancer un backtest (moteur de référence)" wide>
        <DatasetCtx value={ctx} onChange={setCtx} fromCampaign={(r.data as any)?.campaign_id} />
        <div className="row" style={{ alignItems: "center" }}>
          <Field label="Segment"><select value={seg} onChange={(e) => setSeg(e.target.value)}>
            <option value="research">entraînement + validation</option><option value="train">entraînement</option>
            <option value="validation">validation</option><option value="oos">hors échantillon (multiplicité tracée)</option>
          </select></Field>
          <Btn kind="primary" busy={a.busy} disabled={!ctx.dataset_version_id} onClick={() => a.run(() => api.post(`/genomes/${nav.rev}/backtest`, {
            dataset_version_id: ctx.dataset_version_id, context: ctx.context ?? {}, cost_profile: costOf(ctx), segment: seg,
          }), (x) => `Backtest soumis (tâche ${x.task_id}).`)}>Lancer</Btn>
        </div>
        {a.view}
      </Card></div>}
    </div>
  );
}
