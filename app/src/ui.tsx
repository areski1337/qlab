import React, { useCallback, useEffect, useRef, useState } from "react";
import { api } from "./api";

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

export function Card(p: { title?: React.ReactNode; actions?: React.ReactNode; children: React.ReactNode; wide?: boolean }) {
  return (
    <section className={"card" + (p.wide ? " wide" : "")}>
      {(p.title || p.actions) && <header><h3>{p.title}</h3><div className="actions">{p.actions}</div></header>}
      {p.children}
    </section>
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

export function Btn(p: React.ButtonHTMLAttributes<HTMLButtonElement> & { busy?: boolean; kind?: "primary" | "danger" }) {
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

export function Table({ cols, rows, onRow, empty = "Aucune donnée." }: {
  cols: { k: string; t: string; f?: (r: any) => React.ReactNode; num?: boolean }[]; rows: any[] | null; onRow?: (r: any) => void; empty?: string;
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
      <thead><tr>{cols.map((c) => (
        <th key={c.k} className={c.num ? "num" : ""} onClick={() => setSort({ k: c.k, asc: sort?.k === c.k ? !sort.asc : false })}>
          {c.t}{sort?.k === c.k ? (sort.asc ? " ▲" : " ▼") : ""}</th>))}</tr></thead>
      <tbody>{sorted.map((r, i) => (
        <tr key={r.id ?? i} onClick={() => onRow?.(r)} className={onRow ? "click" : ""}>
          {cols.map((c) => <td key={c.k} className={c.num ? "num" : ""}>{c.f ? c.f(r) : fmt(get(r, c.k))}</td>)}
        </tr>))}</tbody>
    </table></div>
  );
}

/** Courbe simple (SVG) avec unités et période affichées. */
export function LineChart({ xs, ys, unit, label, height = 200 }: { xs: number[]; ys: number[]; unit: string; label: string; height?: number }) {
  const ref = useRef<SVGSVGElement>(null);
  const [hover, setHover] = useState<number | null>(null);
  if (!ys.length) return <p className="muted">Pas de données à tracer.</p>;
  const W = 800, H = height, P = 36;
  const lo = Math.min(...ys), hi = Math.max(...ys) === lo ? lo + 1 : Math.max(...ys);
  const X = (i: number) => P + (i / Math.max(1, ys.length - 1)) * (W - 2 * P);
  const Y = (v: number) => H - P - ((v - lo) / (hi - lo)) * (H - 2 * P);
  const d = ys.map((v, i) => `${i ? "L" : "M"}${X(i).toFixed(1)},${Y(v).toFixed(1)}`).join("");
  const onMove = (e: React.MouseEvent) => {
    const r = ref.current!.getBoundingClientRect();
    const i = Math.round(((e.clientX - r.left) / r.width * W - P) / (W - 2 * P) * (ys.length - 1));
    setHover(Math.max(0, Math.min(ys.length - 1, i)));
  };
  return (
    <figure className="chart">
      <svg ref={ref} viewBox={`0 0 ${W} ${H}`} onMouseMove={onMove} onMouseLeave={() => setHover(null)} role="img" aria-label={label}>
        <line x1={P} x2={W - P} y1={H - P} y2={H - P} className="axis" />
        <text x={4} y={Y(hi) + 4} className="tick">{fmt(hi)}</text>
        <text x={4} y={Y(lo) + 4} className="tick">{fmt(lo)}</text>
        <path d={d} className="series" />
        {hover !== null && <>
          <line x1={X(hover)} x2={X(hover)} y1={P / 2} y2={H - P} className="cursor" />
          <circle cx={X(hover)} cy={Y(ys[hover])} r={3} className="dot" />
          <text x={Math.min(X(hover) + 6, W - 200)} y={P / 2 + 10} className="tip">{fmt(ys[hover])} {unit} — {utc(xs[hover])}</text>
        </>}
      </svg>
      <figcaption>{label} · unité : {unit} · {utc(xs[0])} → {utc(xs[xs.length - 1])}</figcaption>
    </figure>
  );
}

/** Nuage de points (front de Pareto). */
export function Scatter({ pts, xl, yl, onPick, highlight }: {
  pts: { x: number; y: number; id: string; front?: boolean }[]; xl: string; yl: string; onPick?: (id: string) => void; highlight?: string;
}) {
  const ok = pts.filter((p) => Number.isFinite(p.x) && Number.isFinite(p.y));
  if (!ok.length) return <p className="muted">Aucun point calculable.</p>;
  const W = 800, H = 340, P = 44;
  const xs = ok.map((p) => p.x), ys = ok.map((p) => p.y);
  const [x0, x1] = [Math.min(...xs), Math.max(...xs) === Math.min(...xs) ? Math.min(...xs) + 1 : Math.max(...xs)];
  const [y0, y1] = [Math.min(...ys), Math.max(...ys) === Math.min(...ys) ? Math.min(...ys) + 1 : Math.max(...ys)];
  const X = (v: number) => P + (v - x0) / (x1 - x0) * (W - 2 * P), Y = (v: number) => H - P - (v - y0) / (y1 - y0) * (H - 2 * P);
  return (
    <figure className="chart">
      <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label={`${yl} en fonction de ${xl}`}>
        <line x1={P} x2={W - P} y1={H - P} y2={H - P} className="axis" />
        <line x1={P} x2={P} y1={P / 2} y2={H - P} className="axis" />
        <text x={W / 2} y={H - 8} className="tick" textAnchor="middle">{xl} ({fmt(x0)} → {fmt(x1)})</text>
        <text x={8} y={16} className="tick">{yl} ({fmt(y0)} → {fmt(y1)})</text>
        {ok.map((p) => (
          <circle key={p.id} cx={X(p.x)} cy={Y(p.y)} r={p.id === highlight ? 6 : p.front ? 4.5 : 3}
            className={"pt" + (p.front ? " front" : "") + (p.id === highlight ? " hl" : "")} onClick={() => onPick?.(p.id)}>
            <title>{p.id} — {xl} {fmt(p.x)}, {yl} {fmt(p.y)}</title>
          </circle>))}
      </svg>
    </figure>
  );
}

export function Json({ v }: { v: any }) {
  return <pre className="json">{JSON.stringify(v, null, 2)}</pre>;
}

export function Field(p: { label: string; children: React.ReactNode; hint?: string }) {
  return <label className="field"><span>{p.label}</span>{p.children}{p.hint && <small className="muted">{p.hint}</small>}</label>;
}

export function Incomplete({ what, why }: { what: string; why: string }) {
  return <div className="alert warn"><strong>Fonction incomplète — {what}.</strong> {why}</div>;
}
