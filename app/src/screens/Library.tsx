import React, { useMemo, useState } from "react";
import { api } from "../api";
import { Badge, Card, Err, fmt, PageHead, Seg, Table, useApi } from "../ui";
import { Explain } from "../charts";
import { Icon } from "../icons";
import { useNav } from "../main";

const COLS: [string, string, number][] = [["sharpe", "Sharpe", 2], ["net_profit", "Profit net", 0], ["return_pct", "Rendement %", 1],
  ["max_dd_pct", "Drawdown max %", 1], ["profit_factor", "Profit factor", 2], ["expectancy_r", "Espérance (R)", 2],
  ["win_rate", "Réussite", 2], ["n_trades", "Trades", 0]];

export function Library() {
  const { go } = useNav();
  const lib = useApi<any[]>("/library", [], true);
  const [filter, setFilter] = useState<"all" | "fav">("all");
  const [tag, setTag] = useState("");
  const [q, setQ] = useState("");
  const [sel, setSel] = useState<string[]>([]);
  const [edit, setEdit] = useState<any>(null);
  const [err, setErr] = useState<string | null>(null);
  const rows = lib.data ?? null;
  const tags = useMemo(() => [...new Set((rows ?? []).flatMap((r) => r.tags))].sort(), [rows]);
  const shown = rows?.filter((r) => (filter === "all" || r.favorite) && (!tag || r.tags.includes(tag))
    && (!q || `${r.id} ${r.note} ${r.tags.join(" ")}`.toLowerCase().includes(q.toLowerCase()))) ?? null;
  const save = async (r: any, patch: any) => {
    try { await api.put(`/genomes/${r.id}/notes`, { favorite: !!r.favorite, tags: r.tags, note: r.note, ...patch }); setErr(null); lib.reload(); }
    catch (e: any) { setErr(e.message); }
  };
  const cmp = (rows ?? []).filter((r) => sel.includes(r.id));
  return (
    <div>
      <PageHead title="Bibliothèque de stratégies" sub="Stratégies retenues ou annotées : favoris, étiquettes, notes, comparaison côte à côte.">
        <Seg label="Filtre" value={filter} onChange={setFilter} options={[["all", "Toutes"], ["fav", "★ Favoris"]]} />
        <select aria-label="Étiquette" value={tag} onChange={(e) => setTag(e.target.value)}><option value="">toutes étiquettes</option>{tags.map((t) => <option key={t}>{t}</option>)}</select>
        <input aria-label="Rechercher" placeholder="rechercher…" value={q} onChange={(e) => setQ(e.target.value)} />
      </PageHead>
      <Err msg={lib.error || err} />
      <div className="grid">
        <Card title={`${shown?.length ?? 0} stratégie(s)`} wide actions={<span className="muted">cocher 2 à 4 stratégies pour les comparer</span>}>
          <Table rows={shown} empty="Aucune stratégie : elles apparaissent ici dès le statut « filtrée », ou dès qu'on les annote." cols={[
            { k: "sel", t: "", f: (r) => <input type="checkbox" aria-label={`Comparer ${r.id}`} checked={sel.includes(r.id)}
              onChange={(e) => setSel(e.target.checked ? [...sel, r.id].slice(-4) : sel.filter((x) => x !== r.id))} /> },
            { k: "favorite", t: "★", f: (r) => <button className="iconbtn" aria-pressed={!!r.favorite} aria-label="Favori" style={{ color: r.favorite ? "var(--warn)" : undefined }}
              onClick={(e) => { e.stopPropagation(); save(r, { favorite: !r.favorite }); }}><Icon n="star" s={16} fill={!!r.favorite} /></button> },
            { k: "id", t: "Révision", f: (r) => <a href="#" onClick={(e) => { e.preventDefault(); go({ screen: "genome", rev: r.id }); }}>{r.id}</a> },
            { k: "status", t: "Statut", f: (r) => <Badge s={r.status} /> },
            { k: "metrics.sharpe", t: "Sharpe", num: true, tone: true }, { k: "metrics.net_profit", t: "Net", num: true, tone: true },
            { k: "metrics.max_dd_pct", t: "DD %", num: true }, { k: "metrics.n_trades", t: "Trades", num: true },
            { k: "tags", t: "Étiquettes", f: (r) => r.tags.map((t: string) => <span key={t} className="badge" style={{ marginRight: 4 }}>{t}</span>) },
            { k: "note", t: "Note", f: (r) => <span className="muted">{r.note.slice(0, 60)}{r.note.length > 60 ? "…" : ""}</span> },
            { k: "edit", t: "", f: (r) => <button className="btn ghost" onClick={() => setEdit({ ...r, tagsTxt: r.tags.join(", ") })}>Annoter</button> }]} />
        </Card>
        {edit && <Card title={`Annoter ${edit.id}`} wide>
          <div className="row">
            <label className="field" style={{ flex: 1 }}><span>Étiquettes (séparées par des virgules)</span>
              <input value={edit.tagsTxt} onChange={(e) => setEdit({ ...edit, tagsTxt: e.target.value })} placeholder="ex. or, tendance, à surveiller" /></label>
          </div>
          <label className="field"><span>Note</span><textarea rows={4} value={edit.note} onChange={(e) => setEdit({ ...edit, note: e.target.value })} /></label>
          <div className="actions">
            <button className="btn primary" onClick={async () => { await save(edit, { tags: edit.tagsTxt.split(","), note: edit.note }); setEdit(null); }}>Enregistrer</button>
            <button className="btn" onClick={() => setEdit(null)}>Annuler</button>
          </div>
        </Card>}
        {cmp.length >= 2 && <Compare key={cmp.map((r) => r.id).join()} ids={cmp.map((r) => r.id)} lib={cmp} />}
      </div>
    </div>
  );
}

function Compare({ ids, lib }: { ids: string[]; lib: any[] }) {
  // un appel de hook par colonne : sûr car le parent remonte ce composant (key) quand la sélection change
  const details = ids.map((id) => useApi<any>(`/genomes/${id}`, [id]));
  const best = (k: string, low = false) => {
    const v = lib.map((r) => r.metrics?.[k]).filter((x) => x != null && Number.isFinite(x));
    return v.length ? (low ? Math.min(...v) : Math.max(...v)) : null;
  };
  return (
    <Card title="Comparaison côte à côte" wide>
      <div className="tablewrap"><table>
        <thead><tr><th></th>{lib.map((r) => <th key={r.id}>{r.id.slice(-8)} <Badge s={r.status} /></th>)}</tr></thead>
        <tbody>
          {COLS.map(([k, l, d]) => {
            const b = best(k, k === "max_dd_pct");
            return <tr key={k}><td className="muted">{l}</td>{lib.map((r) => {
              const v = r.metrics?.[k];
              return <td key={r.id} className="num" style={v != null && v === b ? { color: "var(--acc)", fontWeight: 700 } : undefined}>{fmt(k === "win_rate" && v != null ? v * 100 : v, d)}{k === "win_rate" && v != null ? " %" : ""}</td>;
            })}</tr>;
          })}
          {["marché", "entrée long", "entrée short", "stop", "objectif", "time stop", "gestion"].map((k) => (
            <tr key={k}><td className="muted">{k}</td>{details.map((d, i) => <td key={i} style={{ whiteSpace: "normal", minWidth: 220, verticalAlign: "top", fontSize: 12 }}>{d.data?.description?.[k] ?? "—"}</td>)}</tr>))}
        </tbody>
      </table></div>
      <Explain>En <b>accent</b> : la meilleure valeur de la ligne (drawdown : la plus faible). Métriques de la dernière évaluation de recherche (entraînement + validation) ou, à défaut, d'entraînement : à comparer seulement entre stratégies évaluées sur le même marché et la même période.</Explain>
    </Card>
  );
}
