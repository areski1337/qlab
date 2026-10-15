import React, { useCallback, useEffect, useMemo, useState } from "react";
import { api } from "./api";

export const fmt = (x: any, d = 2) =>
  x === null || x === undefined || Number.isNaN(x) ? "—" : typeof x === "number" ? x.toLocaleString("fr-FR", { maximumFractionDigits: d }) : String(x);
export const utc = (ts?: number) => (ts ? new Date(ts * 1000).toISOString().replace("T", " ").slice(0, 16) + " UTC" : "—");

// Un seul abonnement au flux d'événements : distingue un changement d'état de tâche (rechargement utile partout)
// d'une simple progression (émise à chaque lot d'une campagne : ne recharger que les vues qui l'affichent).
type Change = "state" | "progress";
const subs = new Set<(c: Change) => void>();
const lastState = new Map<string, string>();
let wired = false;
function wire() {
  if (wired) return;
  wired = true;
  window.qlab.onEvent((ev) => {
    if (ev.type === "engine.ready") return subs.forEach((f) => f("state"));
    if (ev.type !== "task.updated") return;
    const t = ev.task ?? {};
    const c: Change = lastState.get(t.id) !== t.state ? "state" : "progress";
    lastState.set(t.id, t.state);
    subs.forEach((f) => f(c));
  });
}

/** Charge une ressource API. `live` : recharge quand une tâche change d'état ; "progress" : aussi sur la
 * progression, au plus toutes les 1,5 s. */
export function useApi<T = any>(path: string | null, deps: any[] = [], live: boolean | "progress" = false) {
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
    wire();
    let t: any = null, last = 0;
    const f = (c: Change) => {
      if (c === "progress" && live !== "progress") return;
      clearTimeout(t);
      const wait = c === "state" ? 400 : Math.max(0, 1500 - (Date.now() - last));
      t = setTimeout(() => { last = Date.now(); reload(); }, wait);
    };
    subs.add(f);
    return () => { subs.delete(f); clearTimeout(t); };
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
const PAGE = 200;  // lignes rendues par page : les grandes listes (5 000 candidats) restent fluides

/** Tableau triable (en-têtes au clavier), paginé, lignes activables au clavier. `tone` : couleur selon le signe. */
export function Table({ cols, rows, onRow, empty = "Aucune donnée." }: {
  cols: { k: string; t: string; f?: (r: any) => React.ReactNode; num?: boolean; tone?: boolean }[]; rows: any[] | null; onRow?: (r: any) => void; empty?: string;
}) {
  const [sort, setSort] = useState<{ k: string; asc: boolean } | null>(null);
  const [page, setPage] = useState(0);
  const get = (r: any, k: string) => k.split(".").reduce((a, x) => (a == null ? a : a[x]), r);
  const sorted = useMemo(() => !rows || !sort ? rows : [...rows].sort((a, b) => {
    const x = get(a, sort.k), y = get(b, sort.k);
    const c = x == null ? 1 : y == null ? -1 : x > y ? 1 : x < y ? -1 : 0;
    return sort.asc ? c : -c;
  }), [rows, sort]);
  if (!sorted) return <p className="muted">Chargement…</p>;
  if (!sorted.length) return <p className="muted">{empty}</p>;
  const pages = Math.ceil(sorted.length / PAGE), p = Math.min(page, pages - 1);
  const view = sorted.slice(p * PAGE, (p + 1) * PAGE);
  return (
    <>
      <div className="tablewrap"><table>
        <thead><tr>{cols.map((c, i) => (
          <th key={c.k + i} className={c.num ? "num" : ""} aria-sort={sort?.k === c.k ? (sort.asc ? "ascending" : "descending") : undefined}>
            <button type="button" className="th" onClick={() => setSort({ k: c.k, asc: sort?.k === c.k ? !sort.asc : false })}>
              {c.t}{sort?.k === c.k ? (sort.asc ? " ▲" : " ▼") : ""}</button></th>))}</tr></thead>
        <tbody>{view.map((r, i) => (
          <tr key={r.id ?? i} onClick={() => onRow?.(r)} className={onRow ? "click" : ""} tabIndex={onRow ? 0 : undefined}
            onKeyDown={onRow ? (e) => { if (e.key === "Enter" && e.target === e.currentTarget) onRow(r); } : undefined}>
            {cols.map((c, j) => {
              const v = get(r, c.k);
              const tone = c.tone && typeof v === "number" ? (v > 0 ? " pos" : v < 0 ? " neg" : "") : "";
              return <td key={c.k + j} className={(c.num ? "num" : "") + tone}>{c.f ? c.f(r) : fmt(v)}</td>;
            })}
          </tr>))}</tbody>
      </table></div>
      {pages > 1 && <div className="pager">
        <span className="muted">{fmt(p * PAGE + 1, 0)}–{fmt(Math.min(sorted.length, (p + 1) * PAGE), 0)} sur {fmt(sorted.length, 0)}</span>
        <button className="btn ghost" disabled={p === 0} onClick={() => setPage(p - 1)}>‹ Précédent</button>
        <button className="btn ghost" disabled={p >= pages - 1} onClick={() => setPage(p + 1)}>Suivant ›</button>
      </div>}
    </>
  );
}

/** Pause / reprise / arrêt d'une tâche. Une campagne s'arrête en quelques secondes (fin du lot en cours) et reprend
 * depuis sa dernière génération ; les autres tâches en cours ne peuvent qu'être arrêtées (le calcul déjà lancé se
 * termine en arrière-plan et son résultat est ignoré). */
export function TaskControls({ t, onDone, compact }: { t: { id: string; kind: string; state: string }; onDone?: (msg: string) => void; compact?: boolean }) {
  const [busy, setBusy] = useState(false);
  const act = async (x: "pause" | "resume" | "cancel", msg: string) => {
    if (x === "cancel" && !window.confirm("Arrêter définitivement cette tâche ? Elle ne pourra pas être reprise.")) return;
    setBusy(true);
    try { await api.post(`/tasks/${t.id}/${x}`); onDone?.(msg); } catch (e: any) { onDone?.(e.message); } finally { setBusy(false); }
  };
  const canPause = t.state === "queued" || (t.state === "running" && t.kind === "campaign");
  const stop = (e: React.MouseEvent) => e.stopPropagation();
  return (
    <span className="actions" onClick={stop}>
      {canPause && <Btn busy={busy} className={compact ? "ghost" : ""} title="Suspendre : reprise possible plus tard" onClick={() => act("pause", "Pause demandée : arrêt à la fin du lot en cours.")}>❚❚ Pause</Btn>}
      {t.state === "paused" && <Btn busy={busy} className={compact ? "ghost" : ""} onClick={() => act("resume", "Reprise : la tâche repart de son dernier point de sauvegarde.")}>▶ Reprendre</Btn>}
      {["queued", "validating", "running", "paused"].includes(t.state) && <Btn kind="danger" busy={busy}
        title={t.state === "running" && t.kind !== "campaign" ? "Le calcul déjà lancé se termine en arrière-plan ; son résultat sera ignoré" : "Arrêt définitif"}
        onClick={() => act("cancel", "Tâche arrêtée.")}>■ Arrêter</Btn>}
    </span>
  );
}

/** Mini-courbe pour tuiles KPI. */
export function Spark({ ys }: { ys: number[] }) {
  const v = ys.filter(Number.isFinite);
  if (v.length < 2) return null;
  const lo = Math.min(...v), hi = Math.max(...v) === lo ? lo + 1 : Math.max(...v);
  const d = v.map((y, i) => `${i ? "L" : "M"}${(i / (v.length - 1) * 100).toFixed(1)},${(36 - (y - lo) / (hi - lo) * 32).toFixed(1)}`).join("");
  const up = v[v.length - 1] >= v[0];
  return (
    <svg className="spark" viewBox="0 0 100 38" preserveAspectRatio="none" aria-hidden="true">
      <path d={d + "L100,38L0,38Z"} style={{ fill: up ? "var(--up)" : "var(--down)", opacity: 0.12 }} />
      <path d={d} fill="none" style={{ stroke: up ? "var(--up)" : "var(--down)" }} strokeWidth={1.5} vectorEffect="non-scaling-stroke" />
    </svg>
  );
}

export function Json({ v }: { v: any }) {
  return <pre className="json">{JSON.stringify(v, null, 2)}</pre>;
}

export function Field(p: { label: string; children: React.ReactNode; hint?: string }) {
  return <label className="field"><span>{p.label}</span>{p.children}{p.hint && <small className="muted">{p.hint}</small>}</label>;
}
