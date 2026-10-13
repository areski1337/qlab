import React, { useCallback, useEffect, useState } from "react";
import { api } from "./api";
import { Spark } from "./charts";

export const fmt = (x: any, d = 2) =>
  x === null || x === undefined || Number.isNaN(x) ? "—" : typeof x === "number" ? x.toLocaleString("fr-FR", { maximumFractionDigits: d }) : String(x);
export const utc = (ts?: number) => (ts ? new Date(ts * 1000).toISOString().replace("T", " ").slice(0, 16) + " UTC" : "—");

/** Charge une ressource API ; recharge sur événement de tâche si `live`. */
export function useApi<T = any>(path: string | null, deps: any[] = [], live = false) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const reload = useCallback(async () => {
    if (!path) return;
    setLoading(true);
    try { setData(await api.get(path)); setError(null); } catch (e: any) { setError(e.message); } finally { setLoading(false); }
  }, [path]);
  useEffect(() => { reload(); }, [reload, ...deps]);
  useEffect(() => {
    if (!live) return;
    let t: any = null;
    const off = window.qlab.onEvent((ev) => {
      if (ev.type === "task.updated" || ev.type === "engine.ready") { clearTimeout(t); t = setTimeout(reload, 400); }
    });
    return () => { off(); clearTimeout(t); };
  }, [live, reload]);
  return { data, error, loading, reload };
}

export function Card(p: { title?: React.ReactNode; actions?: React.ReactNode; children: React.ReactNode; wide?: boolean; span2?: boolean }) {
  return (
    <section className={"card" + (p.wide ? " wide" : "") + (p.span2 ? " span2" : "")}>
      {(p.title || p.actions) && <header><h3>{p.title}</h3><div className="actions">{p.actions}</div></header>}
      {p.children}
    </section>
  );
}

/** En-tête d'écran : titre, sous-titre, actions à droite. */
export function PageHead({ title, sub, children }: { title: string; sub?: React.ReactNode; children?: React.ReactNode }) {
  return (
    <div className="pagehead">
      <div><h1>{title}</h1>{sub && <div className="sub">{sub}</div>}</div>
      <span className="grow" />
      {children}
    </div>
  );
}

/** Tuile KPI : libellé, valeur, contexte, tendance optionnelle. `tone` colore selon le signe ou un verdict. */
export function Tile({ l, v, s, spark, tone, hint }: { l: string; v: React.ReactNode; s?: React.ReactNode; spark?: number[]; tone?: "good" | "bad" | null; hint?: string }) {
  return (
    <div className={"tile" + (tone ? " " + tone : "")} title={hint}>
      <div className="l"><span>{l}</span></div>
      <div className="v">{v}</div>
      {s && <div className="s">{s}</div>}
      {spark && <Spark ys={spark} />}
    </div>
  );
}
export const signTone = (x: number | null | undefined) => (x == null || !Number.isFinite(x) ? null : x >= 0 ? "good" : "bad");

/** Contrôle segmenté. */
export function Seg<T extends string>({ value, options, onChange, label }: { value: T; options: [T, string][]; onChange: (v: T) => void; label?: string }) {
  return (
    <div className="seg" role="radiogroup" aria-label={label}>
      {options.map(([k, l]) => <button key={k} role="radio" aria-checked={value === k} className={value === k ? "on" : ""} onClick={() => onChange(k)}>{l}</button>)}
    </div>
  );
}

export function Err({ msg }: { msg: string | null }) {
  return msg ? <div className="alert err" role="alert">{msg}</div> : null;
}

export const STATUS_FR: Record<string, string> = {
  unverified: "non vérifiée", screened: "filtrée", historically_tested: "testée (historique)",
  robustness_tested: "robustesse testée", oos_evaluated: "évaluée hors échantillon", reference_matched: "concordance référence",
  mt5_validated: "validée MT5", demo_observed: "observée en démo", rejected: "rejetée", quarantined: "quarantaine",
  queued: "en file", validating: "validation", running: "en cours", paused: "en pause", completed: "terminée",
  failed: "échec", cancelled: "annulée",
};

export function Badge({ s }: { s: string }) {
  return <span className={"badge b-" + s}>{STATUS_FR[s] ?? s}</span>;
}

export function Btn(p: React.ButtonHTMLAttributes<HTMLButtonElement> & { busy?: boolean; kind?: "primary" | "danger" | "ghost" }) {
  const { busy, kind, className, ...rest } = p;
  return <button {...rest} className={`btn ${kind ?? ""} ${className ?? ""}`} disabled={p.disabled || busy}>{busy ? "…" : p.children}</button>;
}

/** Lance une action API et affiche le résultat/erreur. */
export function useAction() {
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const run = async (fn: () => Promise<any>, okText?: (r: any) => string) => {
    setBusy(true); setMsg(null);
    try { const r = await fn(); setMsg({ ok: true, text: okText ? okText(r) : "OK" }); return r; }
    catch (e: any) { setMsg({ ok: false, text: e.message }); }
    finally { setBusy(false); }
  };
  const view = msg ? <div className={"alert " + (msg.ok ? "ok" : "err")}>{msg.text}</div> : null;
  return { busy, run, view };
}

/** Tableau triable. `tone` : colonnes numériques colorées selon le signe. */
export function Table({ cols, rows, onRow, empty = "Aucune donnée." }: {
  cols: { k: string; t: string; f?: (r: any) => React.ReactNode; num?: boolean; tone?: boolean }[]; rows: any[] | null; onRow?: (r: any) => void; empty?: string;
}) {
  const [sort, setSort] = useState<{ k: string; asc: boolean } | null>(null);
  if (!rows) return <p className="muted">Chargement…</p>;
  if (!rows.length) return <p className="muted">{empty}</p>;
  const get = (r: any, k: string) => k.split(".").reduce((a, x) => (a == null ? a : a[x]), r);
  const sorted = sort ? [...rows].sort((a, b) => {
    const x = get(a, sort.k), y = get(b, sort.k);
    const c = x == null ? 1 : y == null ? -1 : x > y ? 1 : x < y ? -1 : 0;
    return sort.asc ? c : -c;
  }) : rows;
  return (
    <div className="tablewrap"><table>
      <thead><tr>{cols.map((c, i) => (
        <th key={c.k + i} className={c.num ? "num" : ""} aria-sort={sort?.k === c.k ? (sort.asc ? "ascending" : "descending") : undefined}
          onClick={() => setSort({ k: c.k, asc: sort?.k === c.k ? !sort.asc : false })}>
          {c.t}{sort?.k === c.k ? (sort.asc ? " ▲" : " ▼") : ""}</th>))}</tr></thead>
      <tbody>{sorted.map((r, i) => (
        <tr key={r.id ?? i} onClick={() => onRow?.(r)} className={onRow ? "click" : ""}>
          {cols.map((c, j) => {
            const v = get(r, c.k);
            const tone = c.tone && typeof v === "number" ? (v > 0 ? " pos" : v < 0 ? " neg" : "") : "";
            return <td key={c.k + j} className={(c.num ? "num" : "") + tone}>{c.f ? c.f(r) : fmt(v)}</td>;
          })}
        </tr>))}</tbody>
    </table></div>
  );
}

export function Json({ v }: { v: any }) {
  return <pre className="json">{JSON.stringify(v, null, 2)}</pre>;
}

export function Field(p: { label: string; children: React.ReactNode; hint?: string }) {
  return <label className="field"><span>{p.label}</span>{p.children}{p.hint && <small className="muted">{p.hint}</small>}</label>;
}
