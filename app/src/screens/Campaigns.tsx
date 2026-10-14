import React, { useEffect, useMemo, useRef, useState } from "react";
import { api } from "../api";
import { Badge, Btn, Card, Err, Field, fmt, Json, PageHead, Seg, Table, TaskControls, Tile, useAction, useApi } from "../ui";
import { Bars, Explain, Lines, Scatter } from "../charts";
import { useNav } from "../main";

const TRIBES = [["consistency", "Consistance"], ["growth", "Croissance"], ["exploration", "Exploration"], ["specialization", "Spécialisation"]];
const TRIBE_FR: Record<string, string> = { ...Object.fromEntries(TRIBES), merge: "Fusion" };
const SESSIONS = ["london_kz", "ny_am_kz", "asia_kz", "london_close_kz", "london", "new_york", "tokyo", "ldn_ny_overlap"];
const METRIC_FR: Record<string, string> = {
  sharpe: "Sharpe", max_dd_pct: "Drawdown max %", net_profit: "Profit net", return_pct: "Rendement %", profit_factor: "Profit factor",
  expectancy_r: "Espérance (R)", win_rate: "Taux de réussite", n_trades: "Trades", r2_equity: "Régularité (R² equity)",
};

// Effort de recherche : préréglages (population / générations par tribu / générations de fusion)
const PRESETS: Record<string, { label: string; hint: string; population: number; generations_per_tribe: number; merge_generations: number }> = {
  quick: { label: "Rapide", hint: "aperçu en quelques minutes", population: 12, generations_per_tribe: 8, merge_generations: 4 },
  standard: { label: "Standard", hint: "bon compromis", population: 24, generations_per_tribe: 20, merge_generations: 8 },
  deep: { label: "Approfondie", hint: "plus de diversité, plus long", population: 48, generations_per_tribe: 40, merge_generations: 16 },
};
const HTF_PREF: Record<string, string[]> = { M1: ["M15", "H1"], M5: ["H1", "H4"], M15: ["H1", "H4"], M30: ["H4"], H1: ["H4"] };
const DEFAULT_FORM = {
  name: "", dataset_version_id: "", ctx: "", preset: "standard", bases: ["trend", "reversion", "breakout", "session", "ict", "pullback"],
  tribes: ["consistency", "growth", "exploration", "specialization"], specialization_session: "london_kz",
  population: 24, generations_per_tribe: 20, merge_generations: 8, seed: 42, workers: 4,
  sides: "both", spread: "", commission: 0, slippage: 0, min_trades: 30, max_dd_pct: 30, max_ambiguous_ratio: 0.3,
  auto_validate_top: 5, when: "now", run_at: "", every: "once",
};

/** Stratégies retenues d'une campagne : front final + révisions ayant franchi au moins le filtrage. */
async function retainedOf(cid: string): Promise<string[]> {
  const [c, g] = await Promise.all([api.get(`/campaigns/${cid}`), api.get(`/genomes?campaign=${cid}&limit=5000`)]);
  const front = (c.task?.result?.front ?? []).map((f: any) => f.revision_id);
  // jamais une révision qui a vu le segment hors échantillon (le moteur la refuse) : le test OOS ne doit pas servir à sélectionner
  const seedable = new Map((g as any[]).map((r) => [r.id, ["unverified", "screened", "historically_tested", "robustness_tested"].includes(r.status)]));
  const kept = (g as any[]).filter((r) => r.status !== "unverified" && seedable.get(r.id)).map((r) => r.id);
  return [...new Set([...front, ...kept])].filter((id) => seedable.get(id)).slice(0, 40);
}

export function Campaigns() {
  const { nav, go } = useNav();
  const ds = useApi<any[]>("/datasets", [], true);
  const camps = useApi<any[]>("/campaigns", [], true);
  const bases = useApi<any[]>("/strategy-bases");
  const a = useAction();
  const [extra, setExtra] = useState<string[]>([]);
  const [f, setF] = useState<any>(DEFAULT_FORM);
  const [seedFrom, setSeedFrom] = useState(nav.seedFrom ?? "");
  const [seeds, setSeeds] = useState<string[] | null>(null);
  useEffect(() => { if (nav.seedFrom) go({ ...nav, seedFrom: undefined }); }, []);  // relance consommée : pas de re-préremplissage plus tard
  const set = (k: string) => (e: any) => setF({ ...f, [k]: e.target.type === "number" ? Number(e.target.value) : e.target.value });
  const base = ds.data?.find((d) => d.id === f.dataset_version_id);
  const htfs = ds.data?.filter((d) => base && d.canonical_symbol === base.canonical_symbol && d.timeframe !== base.timeframe) ?? [];
  const needSpread = (base?.qc?.zero_spread_ratio ?? 0) > 0;
  const evals = f.tribes.length * f.population * f.generations_per_tribe + f.population * f.merge_generations;
  const est = useApi<any>(f.dataset_version_id ? `/campaigns/estimate?dataset_version_id=${encodeURIComponent(f.dataset_version_id)}&n=${evals}` : null, [f.dataset_version_id, evals]);

  const pickDataset = (id: string) => {
    const d = ds.data?.find((x) => x.id === id);
    const ctx = d ? ds.data!.find((x) => x.canonical_symbol === d.canonical_symbol && (HTF_PREF[d.timeframe] ?? []).includes(x.timeframe)) : null;
    setF((o: any) => ({ ...o, dataset_version_id: id, ctx: ctx?.id ?? "" }));
  };
  const preset = (k: string) => setF({ ...f, preset: k, population: PRESETS[k].population, generations_per_tribe: PRESETS[k].generations_per_tribe, merge_generations: PRESETS[k].merge_generations });

  // relance : reprend les réglages de la campagne source et ses stratégies retenues
  useEffect(() => {
    setSeeds(null);
    if (!seedFrom) return;
    let live = true;
    (async () => {
      const [c, ids] = await Promise.all([api.get(`/campaigns/${seedFrom}`), retainedOf(seedFrom)]);
      if (!live) return;
      setSeeds(ids);
      const k = c.config;
      const ctx = Object.values(k.context_version_ids ?? {})[0] as string | undefined;
      setF((o: any) => ({
        ...o, name: `${c.name} · relance`, dataset_version_id: k.dataset_version_id, ctx: ctx ?? "", sides: k.sides,
        tribes: k.tribes, specialization_session: k.specialization_session, bases: k.bases?.length ? k.bases : o.bases,
        spread: k.cost_profile?.fixed_spread_points ?? "", commission: k.cost_profile?.commission_per_lot_side ?? 0,
        slippage: k.cost_profile?.slippage_points ?? 0, seed: (k.seed ?? 42) + 1, ...k.constraints,
      }));
    })().catch(() => live && setSeeds([]));
    return () => { live = false; };
  }, [seedFrom]);

  const submit = () => a.run(async () => {
    const cfg: any = {
      name: f.name || `${base?.canonical_symbol} ${base?.timeframe} · ${PRESETS[f.preset]?.label ?? "personnalisée"}`,
      dataset_version_id: f.dataset_version_id, seed: f.seed, population: f.population,
      generations_per_tribe: f.generations_per_tribe, merge_generations: f.merge_generations, tribes: f.tribes,
      specialization_session: f.specialization_session, workers: f.workers, sides: f.sides, bases: f.bases,
      seed_revision_ids: seeds ?? [], auto_validate_top: f.auto_validate_top,
      context_version_ids: f.ctx ? { [ds.data!.find((d) => d.id === f.ctx).timeframe]: f.ctx } : {},
      constraints: { min_trades: f.min_trades, max_dd_pct: f.max_dd_pct, max_ambiguous_ratio: f.max_ambiguous_ratio },
      cost_profile: {
        name: "ui", version: 1, spread_mode: "max", fixed_spread_points: f.spread === "" ? null : Number(f.spread),
        commission_per_lot_side: f.commission, slippage_points: f.slippage, apply_swap: true,
        provenance: { spread: "assumed", commission: "assumed", slippage: "assumed", swap: "symbol_spec" },
      },
    };
    if (f.when === "later") {
      if (!f.run_at) throw new Error("choisir la date et l'heure de lancement");
      const s = await api.post("/schedules", { name: cfg.name, kind: "campaign", payload: cfg, every: f.every, first_run_utc: new Date(f.run_at).toISOString() });
      go({ screen: "tasks" });
      return { ...s, scheduled: true };
    }
    const r = await api.post("/campaigns", { config: cfg });
    // campagnes supplémentaires : mêmes réglages, un dataset par symbole (sans contexte HTF spécifique)
    for (const d of extra) await api.post("/campaigns", { config: { ...cfg, name: `${cfg.name} · ${ds.data!.find((x) => x.id === d)?.canonical_symbol}`, dataset_version_id: d, context_version_ids: {} } });
    go({ screen: "lab", campaign: r.campaign_id });
    return r;
  });
  return (
    <div>
      <PageHead title="Campagnes" sub="Recherche génétique sur entraînement + validation. Les segments hors échantillon et final restent scellés." />
      <div className="grid">
        <Card title="Nouvelle campagne" wide actions={<span className={evals > 50000 ? "real-off" : "muted"} style={{ fontFamily: "var(--font-num)" }}>≈ {fmt(evals, 0)} évaluations</span>}>
          {est.data && <div className="alert">
            <b>Budget d'essais.</b> Cette série compte déjà {fmt(est.data.previous_trials_on_series, 0)} stratégie(s) essayée(s) ; avec ≈ {fmt(est.data.planned_trials, 0)} de plus,
            le Sharpe dégonflé exigera un Sharpe annualisé d'environ <b>{fmt(est.data.required_sharpe_annual, 2)}</b> sur {fmt(est.data.train_days, 0)} jours d'entraînement
            (maximum attendu par pur hasard : {fmt(est.data.sr0_annual, 2)} ; dispersion {est.data.sd_source}). Moins d'essais ou un historique plus long abaissent ce seuil.
            {est.data.segments && <><br /><b>Segments{est.data.segments.frozen ? " (figés pour cette série)" : " (seront figés à la première évaluation)"}.</b> Entraînement jusqu'au {est.data.segments.train_end?.slice(0, 10) ?? "—"}, validation jusqu'au {est.data.segments.validation_end?.slice(0, 10) ?? "—"}, hors échantillon jusqu'au {est.data.segments.oos_end?.slice(0, 10) ?? "—"}, final jusqu'au {est.data.segments.final_end?.slice(0, 10) ?? "—"}.</>}
          </div>}
          {evals > 50000 && <div className="alert warn">Campagne très lourde (≈ {fmt(evals, 0)} backtests) : plusieurs heures à plusieurs jours selon la taille du dataset. Préférer « Standard » puis relancer depuis les meilleures stratégies.</div>}
          <h3>1 · Marché</h3>
          <div className="row">
            <Field label="Instrument et timeframe">
              <select value={f.dataset_version_id} onChange={(e) => pickDataset(e.target.value)}>
                <option value="">— choisir —</option>
                {ds.data?.map((d) => <option key={d.id} value={d.id}>{d.canonical_symbol} {d.timeframe} · {fmt(d.n_bars, 0)} barres{d.synthetic ? " [SYNTHÉTIQUE]" : ""}</option>)}
              </select>
            </Field>
            <Field label="Contexte supérieur" hint={f.ctx ? "choisi automatiquement" : undefined}>
              <select value={f.ctx} onChange={set("ctx")}>
                <option value="">aucun</option>
                {htfs.map((d) => <option key={d.id} value={d.id}>{d.timeframe} v{d.version}</option>)}
              </select>
            </Field>
            <Field label="Sens"><Seg label="Sens" value={f.sides} onChange={(v) => setF({ ...f, sides: v })} options={[["both", "Long + short"], ["long", "Long"], ["short", "Short"]]} /></Field>
            {needSpread && <Field label="Spread minimal (points)" hint="données sans spread sur certaines barres : requis"><input type="number" value={f.spread} onChange={set("spread")} placeholder="ex. 20" /></Field>}
          </div>
          <h3>2 · Bases de stratégie</h3>
          <div className="row" style={{ gap: 6 }}>
            {bases.data?.map((b) => {
              const on = f.bases.includes(b.id);
              return <button key={b.id} type="button" className={"btn" + (on ? " primary" : "")} title={b.description} aria-pressed={on}
                onClick={() => setF({ ...f, bases: on ? f.bases.filter((x: string) => x !== b.id) : [...f.bases, b.id] })}>{b.label}</button>;
            })}
          </div>
          <p className="muted" style={{ margin: "6px 0 0" }}>{f.bases.length ? `Population de départ : 60 % construits sur ${f.bases.length} base(s) choisie(s), 40 % aléatoires (exploration). Survoler une base pour sa logique.` : "Aucune base : population de départ entièrement aléatoire."}</p>
          <h3>3 · Repartir de stratégies existantes (optionnel)</h3>
          <div className="row">
            <Field label="Campagne source">
              <select value={seedFrom} onChange={(e) => setSeedFrom(e.target.value)}>
                <option value="">— partir de zéro —</option>
                {camps.data?.map((c) => <option key={c.id} value={c.id}>{c.name} · {c.id}</option>)}
              </select>
            </Field>
            {seedFrom && <span className="muted" style={{ paddingBottom: 14 }}>{seeds == null ? "chargement…" : seeds.length
              ? `${seeds.length} stratégie(s) retenue(s) reprises comme point de départ (au plus la moitié de chaque tribu ; jamais celles déjà testées hors échantillon) ; réglages de la campagne source repris.`
              : "aucune stratégie retenue dans cette campagne : départ de zéro."}</span>}
          </div>
          <h3>4 · Effort</h3>
          <div className="row" style={{ alignItems: "center" }}>
            <Seg label="Effort" value={f.preset} onChange={preset} options={Object.entries(PRESETS).map(([k, p]) => [k, p.label]) as any} />
            <span className="muted">{PRESETS[f.preset]?.hint ?? "réglages personnalisés"}</span>
          </div>
          <h3>5 · Validation et lancement</h3>
          <div className="row" style={{ alignItems: "flex-end" }}>
            <Field label="Valider automatiquement les N meilleures" hint="0 = non ; filtrage → historique → robustesse → hors échantillon">
              <input type="number" min={0} max={20} value={f.auto_validate_top} onChange={set("auto_validate_top")} /></Field>
            <Field label="Lancement"><Seg label="Lancement" value={f.when} onChange={(v) => setF({ ...f, when: v })} options={[["now", "Maintenant"], ["later", "Programmer"]]} /></Field>
            {f.when === "later" && <>
              <Field label="Date et heure (heure locale)"><input type="datetime-local" value={f.run_at} onChange={set("run_at")} /></Field>
              <Field label="Répéter"><select value={f.every} onChange={set("every")}><option value="once">une fois</option><option value="daily">chaque jour</option><option value="weekly">chaque semaine</option></select></Field>
            </>}
          </div>
          <details style={{ marginTop: 10 }}>
            <summary className="muted" style={{ cursor: "pointer" }}>Options avancées</summary>
            <div className="row" style={{ marginTop: 8 }}>
              <Field label="Nom"><input value={f.name} onChange={set("name")} placeholder="automatique" /></Field>
              <Field label="Lancer aussi sur (multi-symboles)">
                <select multiple size={3} value={extra} onChange={(e) => setExtra(Array.from(e.target.selectedOptions).map((o) => o.value))}>
                  {ds.data?.filter((d) => base && d.timeframe === base.timeframe && d.id !== base.id).map((d) => <option key={d.id} value={d.id}>{d.canonical_symbol} {d.timeframe} v{d.version}</option>)}
                </select>
              </Field>
            </div>
            <div className="row">
              {TRIBES.map(([k, l]) => (
                <label key={k}><input type="checkbox" checked={f.tribes.includes(k)}
                  onChange={(e) => setF({ ...f, tribes: e.target.checked ? [...f.tribes, k] : f.tribes.filter((x: string) => x !== k) })} /> {l}</label>))}
              <Field label="Session de spécialisation"><select value={f.specialization_session} onChange={set("specialization_session")}>{SESSIONS.map((s) => <option key={s}>{s}</option>)}</select></Field>
            </div>
            <div className="row">
              <Field label="Population / tribu"><input type="number" min={4} max={500} value={f.population} onChange={(e) => setF({ ...f, preset: "", population: Number(e.target.value) })} /></Field>
              <Field label="Générations / tribu"><input type="number" min={1} max={500} value={f.generations_per_tribe} onChange={(e) => setF({ ...f, preset: "", generations_per_tribe: Number(e.target.value) })} /></Field>
              <Field label="Générations de fusion"><input type="number" min={0} max={200} value={f.merge_generations} onChange={(e) => setF({ ...f, preset: "", merge_generations: Number(e.target.value) })} /></Field>
              <Field label="Graine"><input type="number" value={f.seed} onChange={set("seed")} /></Field>
              <Field label="Processus parallèles"><input type="number" min={0} max={64} value={f.workers} onChange={set("workers")} /></Field>
            </div>
            <div className="row">
              {!needSpread && <Field label="Spread plancher (points)" hint="optionnel : max(spread historique, plancher)"><input type="number" value={f.spread} onChange={set("spread")} /></Field>}
              <Field label="Commission / lot / côté"><input type="number" step="0.01" value={f.commission} onChange={set("commission")} /></Field>
              <Field label="Glissement (points)"><input type="number" value={f.slippage} onChange={set("slippage")} /></Field>
              <Field label="Trades min (train)"><input type="number" value={f.min_trades} onChange={set("min_trades")} /></Field>
              <Field label="DD max %"><input type="number" value={f.max_dd_pct} onChange={set("max_dd_pct")} /></Field>
            </div>
          </details>
          <div className="actions" style={{ marginTop: 12 }}>
            <Btn kind="primary" busy={a.busy} disabled={!f.dataset_version_id || !f.tribes.length || (needSpread && f.spread === "") || (!!seedFrom && seeds == null)} onClick={submit}>
              {f.when === "later" ? "Programmer la campagne" : `Lancer la campagne${extra.length ? ` (+${extra.length})` : ""}`}</Btn>
            <span className="muted">Aucune campagne ne peut envoyer d'ordre.</span>
          </div>
          {a.view}
        </Card>
        <Card title="Campagnes" wide>
          <Err msg={camps.error} />
          <Table rows={camps.data} onRow={(r) => go({ screen: "lab", campaign: r.id })} cols={[
            { k: "name", t: "Nom", f: (r) => <b>{r.name}</b> }, { k: "id", t: "ID" }, { k: "task_state", t: "État", f: (r) => <Badge s={r.task_state} /> },
            { k: "progress", t: "Progression", f: (r) => <div style={{ display: "flex", gap: 8, alignItems: "center", minWidth: 140 }}><div className="progress" style={{ flex: 1 }}><i style={{ width: `${r.progress * 100}%` }} /></div>{fmt(r.progress * 100, 0)} %</div> },
            { k: "n_candidates", t: "Candidats", num: true }, { k: "created_at", t: "Créée (UTC)" },
            { k: "act", t: "", f: (r) => <button className="btn" onClick={(e) => { e.stopPropagation(); setSeedFrom(r.id); window.scrollTo(0, 0); document.querySelector("main")?.scrollTo(0, 0); }}>Relancer</button> }]} />
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
  const { nav, go } = useNav();
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
  const [msg, setMsg] = useState<string | null>(null);
  // temps restant estimé d'après la vitesse observée depuis l'ouverture de l'écran (aucune donnée inventée avant 2 mesures)
  const seen = useRef<{ t: number; p: number } | null>(null);
  const eta = (p: number) => {
    const now = Date.now();
    if (!seen.current || p < seen.current.p) { seen.current = { t: now, p }; return null; }
    const rate = (p - seen.current.p) / (now - seen.current.t);
    if (rate <= 0 || p >= 1) return null;
    const m = Math.round((1 - p) / rate / 60000);
    return m < 120 ? `≈ ${m} min restantes` : m < 2880 ? `≈ ${fmt(m / 60, 1)} h restantes` : `≈ ${fmt(m / 1440, 1)} jours restants`;
  };
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
          <Tile l="Progression" v={`${fmt(d.task.progress * 100, 1)} %`} s={<>{eta(d.task.progress) ?? "estimation après quelques lots…"}<div className="progress"><i style={{ width: `${d.task.progress * 100}%` }} /></div></>} />
          <Tile l="Candidats" v={fmt(d.n_candidates, 0)} s="révisions générées" />
          <Tile l="Évaluations" v={fmt(d.n_evaluations, 0)} s="backtests exécutés" />
          <Tile l="Front final" v={fmt(d.task.result?.front?.length ?? 0, 0)} s="non dominés après fusion" />
        </div>
        <div className="grid">
          {msg && <div className="alert ok" style={{ gridColumn: "1 / -1" }}>{msg}</div>}
          <Card title={d.name} wide actions={<>
            <Btn disabled={d.task.state !== "completed"} title="Nouvelle campagne partant des stratégies retenues de celle-ci" onClick={() => go({ screen: "campaigns", seedFrom: d.id })}>Relancer depuis cette campagne</Btn>
            <TaskControls t={{ id: d.task_id, kind: "campaign", state: d.task.state }} onDone={(m) => { setMsg(m); c.reload(); }} />
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
          {d.task.state === "completed" && <Funnel cid={d.id} />}
        </div>
      </>}
    </div>
  );
}

function Funnel({ cid }: { cid: string }) {
  const r = useApi<any>(`/campaigns/${cid}/funnel`, [cid]);
  const x = r.data;
  if (!x) return null;
  const steps: [string, string][] = [["unverified", "Candidats"], ["screened", "Filtrés"], ["historically_tested", "Historique"],
    ["robustness_tested", "Robustesse"], ["oos_evaluated", "Hors échantillon"], ["mt5_validated", "Validés MT5"]];
  return (
    <Card title="Entonnoir de validation" wide>
      <Bars unit="stratégies" items={steps.map(([k, l]) => ({ label: l, value: x.reached?.[k] ?? 0 }))} />
      {x.dominant_cause && <div className="alert warn">Cause de rejet dominante : <b>{x.dominant_cause}</b>{x.advice ? ` — ${x.advice}.` : ""}</div>}
      <Json v={{ rejets: x.rejection_reasons, criteres_robustesse_en_echec: x.failed_robustness_checks }} />
      <Explain>Nombre de stratégies de la campagne ayant atteint chaque étape. Les stratégies non soumises à la validation restent au premier palier.</Explain>
    </Card>
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
