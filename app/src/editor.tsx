// Éditeur visuel de stratégie : arbre de conditions (ET / OU / NON, comparaisons, événements), sorties, gestion.
// Produit un génome qlab.genome/1.0 ; la validation de référence reste celle du moteur (/genomes/validate).
import React, { useEffect, useState } from "react";
import { api } from "./api";
import { Field, Seg, useApi } from "./ui";

type Feat = { name: string; family: string; description: string; outputs: Record<string, string>;
  params: Record<string, { kind: string; lo: number | null; hi: number | null; default: any; choices: any[] }> };
const TFS = ["M1", "M5", "M15", "M30", "H1", "H4"];
const CMP: [string, string][] = [["gt", "est au-dessus de"], ["lt", "est en dessous de"], ["cross_above", "croise au-dessus"], ["cross_below", "croise en dessous"]];

export const EMPTY_GENOME = {
  schema: "qlab.genome/1.0", market: { symbol: "XAUUSD", timeframe: "M15" },
  entry: { long: { id: "n1", op: "compare", left: { feature: "rsi", params: { period: 14 }, output: "value" }, cmp: "gt", right: { const: 50 } }, short: null },
  exit: { stop: { type: "atr", period: 14, mult: 2 }, target: { type: "rr", rr: 2 }, break_even: null, trailing: null, time_stop_bars: null, exit_on_opposite: false },
  sizing: { risk_pct: 0.5 }, management: { max_trades_per_day: 3, cooldown_bars: 0 },
};

/** Identifiants n1, n2… dans l'ordre de l'arbre (le moteur renumérote aussi à la création). */
export function renumber(g: any) {
  let k = 0;
  const walk = (n: any): any => n && ({ ...n, id: `n${++k}`, ...(n.children ? { children: n.children.map(walk) } : {}) });
  return { ...g, entry: { long: walk(g.entry.long), short: walk(g.entry.short) } };
}

const defaults = (f: Feat) => Object.fromEntries(Object.entries(f.params).map(([k, p]) => [k, p.kind === "choice" ? p.choices[0] : p.default]));

function RefEdit({ r, feats, onChange, bool, base }: { r: any; feats: Feat[]; onChange: (r: any) => void; bool: boolean; base: string }) {
  const ok = feats.filter((f) => Object.values(f.outputs).some((k) => (k === "bool") === bool));
  const f = feats.find((x) => x.name === r.feature);
  const outs = f ? Object.entries(f.outputs).filter(([, k]) => (k === "bool") === bool).map(([o]) => o) : [];
  return (
    <span className="ref">
      <select aria-label="Indicateur" value={r.feature} title={f?.description} onChange={(e) => {
        const nf = feats.find((x) => x.name === e.target.value)!;
        onChange({ feature: nf.name, params: defaults(nf), output: Object.entries(nf.outputs).find(([, k]) => (k === "bool") === bool)![0] });
      }}>{ok.map((x) => <option key={x.name} value={x.name}>{x.name}</option>)}</select>
      {outs.length > 1 && <select aria-label="Sortie" value={r.output} onChange={(e) => onChange({ ...r, output: e.target.value })}>{outs.map((o) => <option key={o}>{o}</option>)}</select>}
      {f && Object.entries(f.params).map(([k, p]) => (
        <label key={k} className="pp">{k}
          {p.kind === "choice" || p.kind === "symbol"
            ? <select value={r.params[k] ?? ""} onChange={(e) => onChange({ ...r, params: { ...r.params, [k]: e.target.value } })}>
                {(p.choices.length ? p.choices : [r.params[k]]).map((c: any) => <option key={c}>{c}</option>)}</select>
            : <input type="number" style={{ width: 70 }} step={p.kind === "int" ? 1 : 0.1} min={p.lo ?? undefined} max={p.hi ?? undefined} value={r.params[k] ?? ""}
                onChange={(e) => onChange({ ...r, params: { ...r.params, [k]: p.kind === "int" ? parseInt(e.target.value || "0") : Number(e.target.value) } })} />}
        </label>))}
      <select aria-label="Timeframe" value={r.tf ?? ""} title="timeframe (vide = celui de la stratégie)" onChange={(e) => { const { tf, ...rest } = r; onChange(e.target.value ? { ...rest, tf: e.target.value } : rest); }}>
        <option value="">{base}</option>{TFS.filter((t) => TFS.indexOf(t) > TFS.indexOf(base)).map((t) => <option key={t}>{t}</option>)}
      </select>
    </span>
  );
}

function NodeEdit({ n, feats, onChange, onRemove, base, depth = 0 }: { n: any; feats: Feat[]; onChange: (n: any) => void; onRemove?: () => void; base: string; depth?: number }) {
  const leaf = (kind: "compare" | "event") => kind === "compare"
    ? { id: "n0", op: "compare", left: { feature: "rsi", params: { period: 14 }, output: "value" }, cmp: "gt", right: { const: 50 } }
    : { id: "n0", op: "event", ref: { feature: "session", params: { name: "london" }, output: "active" } };
  const kids = n.children ?? [];
  const head = (
    <span className="nodehead">
      <select aria-label="Type de bloc" value={n.op} onChange={(e) => {
        const op = e.target.value;
        if (op === n.op) return;
        if (["and", "or", "not"].includes(op)) onChange(["and", "or", "not"].includes(n.op) ? { ...n, op, children: op === "not" ? kids.slice(0, 1) : kids.length >= 2 ? kids : [...kids, leaf("compare"), leaf("compare")].slice(0, 2) }
          : { id: "n0", op, children: op === "not" ? [n] : [n, leaf("compare")] });
        else onChange(leaf(op as any));
      }}>
        <option value="compare">Comparaison</option><option value="event">Événement</option>
        <option value="and">Toutes (ET)</option><option value="or">Au moins une (OU)</option><option value="not">Pas (NON)</option>
      </select>
      {onRemove && <button type="button" className="btn ghost" aria-label="Supprimer le bloc" onClick={onRemove}>✕</button>}
    </span>
  );
  if (n.op === "compare") return (
    <div className="node">{head}
      <RefEdit r={n.left} feats={feats} bool={false} base={base} onChange={(left) => onChange({ ...n, left })} />
      <select aria-label="Comparateur" value={n.cmp} onChange={(e) => onChange({ ...n, cmp: e.target.value })}>{CMP.map(([k, l]) => <option key={k} value={k}>{l}</option>)}</select>
      <Seg label="Opérande" value={"const" in n.right ? "c" : "r"} options={[["c", "valeur"], ["r", "indicateur"]]}
        onChange={(v) => onChange({ ...n, right: v === "c" ? { const: 0 } : { feature: "ema", params: { period: 50 }, output: "value" } })} />
      {"const" in n.right
        ? <input type="number" aria-label="Valeur" style={{ width: 90 }} value={n.right.const} onChange={(e) => onChange({ ...n, right: { const: Number(e.target.value) } })} />
        : <RefEdit r={n.right} feats={feats} bool={false} base={base} onChange={(right) => onChange({ ...n, right })} />}
    </div>);
  if (n.op === "event") return (
    <div className="node">{head}<span className="muted">se produit :</span>
      <RefEdit r={n.ref} feats={feats} bool base={base} onChange={(ref) => onChange({ ...n, ref })} /></div>);
  return (
    <div className={"node group d" + (depth % 2)}>{head}
      <div className="kids">
        {kids.map((c: any, i: number) => <NodeEdit key={i} n={c} feats={feats} base={base} depth={depth + 1}
          onChange={(x) => onChange({ ...n, children: kids.map((k: any, j: number) => (j === i ? x : k)) })}
          onRemove={kids.length > (n.op === "not" ? 1 : 2) ? () => onChange({ ...n, children: kids.filter((_: any, j: number) => j !== i) }) : undefined} />)}
        {n.op !== "not" && <div className="actions">
          <button type="button" className="btn ghost" onClick={() => onChange({ ...n, children: [...kids, leaf("compare")] })}>+ comparaison</button>
          <button type="button" className="btn ghost" onClick={() => onChange({ ...n, children: [...kids, leaf("event")] })}>+ événement</button>
        </div>}
      </div>
    </div>);
}

const num = (v: string) => (v === "" ? null : Number(v));

export function GenomeEditor({ g, onChange }: { g: any; onChange: (g: any) => void }) {
  const fs = useApi<Feat[]>("/features");
  const [check, setCheck] = useState<any>(null);
  useEffect(() => {
    const t = setTimeout(() => api.post("/genomes/validate", { genome: renumber(g) }).then(setCheck).catch(() => setCheck(null)), 400);
    return () => clearTimeout(t);
  }, [g]);
  if (!fs.data) return <p className="muted">Chargement des indicateurs…</p>;
  const feats = fs.data, base = g.market.timeframe, ex = g.exit;
  const setEx = (x: any) => onChange({ ...g, exit: { ...ex, ...x } });
  const side = (s: "long" | "short", label: string) => (
    <div className="side-ed">
      <label><input type="checkbox" checked={!!g.entry[s]} onChange={(e) => onChange({ ...g, entry: { ...g.entry, [s]: e.target.checked ? EMPTY_GENOME.entry.long : null } })} /> <b>{label}</b></label>
      {g.entry[s] && <NodeEdit n={g.entry[s]} feats={feats} base={base} onChange={(n) => onChange({ ...g, entry: { ...g.entry, [s]: n } })} />}
    </div>);
  return (
    <div className="editor">
      <div className="row">
        <Field label="Symbole"><input value={g.market.symbol} onChange={(e) => onChange({ ...g, market: { ...g.market, symbol: e.target.value.toUpperCase() } })} /></Field>
        <Field label="Timeframe"><select value={base} onChange={(e) => onChange({ ...g, market: { ...g.market, timeframe: e.target.value } })}>{TFS.map((t) => <option key={t}>{t}</option>)}</select></Field>
      </div>
      <h3>Entrée — conditions évaluées à la clôture de chaque barre</h3>
      {side("long", "Achat (long)")}
      {side("short", "Vente (short)")}
      <h3>Sorties</h3>
      <div className="row">
        <Field label="Stop">
          <select value={ex.stop.type} onChange={(e) => setEx({ stop: e.target.value === "atr" ? { type: "atr", period: 14, mult: 2 } : e.target.value === "swing" ? { type: "swing", left: 3, right: 3, buffer_atr: 0.1 } : { type: "points", points: 300 } })}>
            <option value="atr">multiple d'ATR</option><option value="swing">dernier swing</option><option value="points">points fixes</option></select></Field>
        {ex.stop.type === "atr" && <><Field label="ATR période"><input type="number" value={ex.stop.period} onChange={(e) => setEx({ stop: { ...ex.stop, period: Number(e.target.value) } })} /></Field>
          <Field label="× ATR"><input type="number" step={0.1} value={ex.stop.mult} onChange={(e) => setEx({ stop: { ...ex.stop, mult: Number(e.target.value) } })} /></Field></>}
        {ex.stop.type === "swing" && <><Field label="Swing gauche"><input type="number" value={ex.stop.left} onChange={(e) => setEx({ stop: { ...ex.stop, left: Number(e.target.value) } })} /></Field>
          <Field label="Swing droite"><input type="number" value={ex.stop.right} onChange={(e) => setEx({ stop: { ...ex.stop, right: Number(e.target.value) } })} /></Field>
          <Field label="Marge (× ATR)"><input type="number" step={0.05} value={ex.stop.buffer_atr} onChange={(e) => setEx({ stop: { ...ex.stop, buffer_atr: Number(e.target.value) } })} /></Field></>}
        {ex.stop.type === "points" && <Field label="Points"><input type="number" value={ex.stop.points} onChange={(e) => setEx({ stop: { ...ex.stop, points: Number(e.target.value) } })} /></Field>}
        <Field label="Objectif (R, vide = aucun)"><input type="number" step={0.1} value={ex.target?.type === "rr" ? ex.target.rr : ""} onChange={(e) => setEx({ target: e.target.value === "" ? null : { type: "rr", rr: Number(e.target.value) } })} /></Field>
        <Field label="Break-even à (R, vide = non)"><input type="number" step={0.1} value={ex.break_even?.at_r ?? ""} onChange={(e) => setEx({ break_even: e.target.value === "" ? null : { at_r: Number(e.target.value) } })} /></Field>
        <Field label="Trailing × ATR (vide = non)"><input type="number" step={0.1} value={ex.trailing?.mult ?? ""} onChange={(e) => setEx({ trailing: e.target.value === "" ? null : { period: 14, mult: Number(e.target.value), activate_r: ex.trailing?.activate_r ?? 1 } })} /></Field>
        <Field label="Sortie après (barres, vide = non)"><input type="number" value={ex.time_stop_bars ?? ""} onChange={(e) => setEx({ time_stop_bars: num(e.target.value) })} /></Field>
        <label><input type="checkbox" checked={ex.exit_on_opposite} onChange={(e) => setEx({ exit_on_opposite: e.target.checked })} /> sortie sur signal opposé</label>
      </div>
      <h3>Risque et gestion</h3>
      <div className="row">
        <Field label="Risque demandé / trade (%)" hint="plafonné par le contrôleur de risque"><input type="number" step={0.1} value={g.sizing.risk_pct} onChange={(e) => onChange({ ...g, sizing: { risk_pct: Number(e.target.value) } })} /></Field>
        <Field label="Trades max / jour"><input type="number" value={g.management.max_trades_per_day} onChange={(e) => onChange({ ...g, management: { ...g.management, max_trades_per_day: Number(e.target.value) } })} /></Field>
        <Field label="Pause après un trade (barres)"><input type="number" value={g.management.cooldown_bars} onChange={(e) => onChange({ ...g, management: { ...g.management, cooldown_bars: Number(e.target.value) } })} /></Field>
      </div>
      {check && (check.valid
        ? <div className="alert ok"><b>Stratégie valide.</b>{check.description && <dl className="kv rules" style={{ marginTop: 6 }}>{Object.entries(check.description).map(([k, v]) => <React.Fragment key={k}><dt>{k}</dt><dd>{String(v)}</dd></React.Fragment>)}</dl>}</div>
        : <div className="alert err">{check.errors.map((e: string, i: number) => <div key={i}>{e}</div>)}</div>)}
    </div>
  );
}
