// Graphiques : canvas TradingView (lightweight-charts, Apache-2.0) pour les séries temporelles ;
// SVG pour les graphiques explicatifs (barres, distributions, intervalles, cartes de chaleur).
// Toujours afficher unité et période ; jamais de point inventé : les valeurs absentes restent absentes.
import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  AreaSeries, BarSeries, BaselineSeries, CandlestickSeries, ColorType, createChart, createSeriesMarkers, CrosshairMode,
  HistogramSeries, IChartApi, LineSeries, LineStyle, SeriesMarker, Time, UTCTimestamp,
} from "lightweight-charts";
import { themeColors, usePrefs } from "./prefs";
import { Icon } from "./icons";

const fmtN = (x: number | null | undefined, d = 2) =>
  x == null || !Number.isFinite(x) ? "—" : x.toLocaleString("fr-FR", { maximumFractionDigits: d });
const utcS = (t: number) => new Date(t * 1000).toISOString().replace("T", " ").slice(0, 16);

/** Points triés, temps strictement croissants (dernier gagnant), valeurs finies uniquement. */
export function clean<T extends { time: number }>(pts: T[], ok: (p: T) => boolean = () => true): T[] {
  const m = new Map<number, T>();
  for (const p of pts) if (Number.isFinite(p.time) && ok(p)) m.set(Math.floor(p.time), { ...p, time: Math.floor(p.time) });
  return [...m.values()].sort((a, b) => a.time - b.time);
}

/** « Lecture » : comment lire le graphique, en une ou deux phrases. */
/** Encadré de lecture ; `always` : contient une hypothèse ou une limite, affiché même si les encadrés sont masqués. */
export function Explain({ children, always }: { children: React.ReactNode; always?: boolean }) {
  const { p } = usePrefs();
  return p.explain || always ? <div className="explain"><Icon n="info" s={15} /><div>{children}</div></div> : null;
}

function useTvChart(height: number, deps: any[], build: (c: IChartApi, col: ReturnType<typeof themeColors>) => (() => void) | void) {
  const ref = useRef<HTMLDivElement>(null);
  const { p } = usePrefs();
  useEffect(() => {
    if (!ref.current) return;
    const col = themeColors();
    const chart = createChart(ref.current, {
      autoSize: true, height,
      layout: { background: { type: ColorType.Solid, color: "transparent" }, textColor: col.mut, fontFamily: col.font, fontSize: 11,
        attributionLogo: true, panes: { separatorColor: col.bd, separatorHoverColor: col.acc } },
      grid: { vertLines: { color: p.grid ? col.grid : "transparent" }, horzLines: { color: p.grid ? col.grid : "transparent" } },
      rightPriceScale: { borderColor: col.bd }, timeScale: { borderColor: col.bd, timeVisible: true, secondsVisible: false },
      crosshair: { mode: p.magnet ? CrosshairMode.Magnet : CrosshairMode.Normal,
        vertLine: { color: col.mut, labelBackgroundColor: col.acc, style: LineStyle.Dashed },
        horzLine: { color: col.mut, labelBackgroundColor: col.acc, style: LineStyle.Dashed } },
      localization: { locale: "fr-FR", timeFormatter: (t: number) => utcS(t) + " UTC" },
    });
    const off = build(chart, col);
    chart.timeScale().fitContent();
    return () => { off?.(); chart.remove(); };
  }, [height, p.theme, p.candles, p.accent, p.grid, p.magnet, p.chartType, ...deps]);
  return ref;
}

export type Ohlc = { ts: number[]; open: number[]; high: number[]; low: number[]; close: number[] };
export type Trade = { entry_ts: number; exit_ts: number; entry: number; exit: number; dir: number; pnl: number; r?: number; reason?: string };

/** Prix (bougies / barres / ligne / aire selon préférences) avec entrées-sorties de trades en marqueurs. */
export function PriceChart({ bars, trades = [], height = 380, unit = "prix Bid" }: { bars: Ohlc; trades?: Trade[]; height?: number; unit?: string }) {
  const { p } = usePrefs();
  const [leg, setLeg] = useState<any>(null);
  const ref = useTvChart(height, [bars, trades], (chart, col) => {
    const data = clean(bars.ts.map((t, i) => ({ time: t, open: bars.open[i], high: bars.high[i], low: bars.low[i], close: bars.close[i] })),
      (b) => [b.open, b.high, b.low, b.close].every(Number.isFinite));
    const s = p.chartType === "candles" ? chart.addSeries(CandlestickSeries, { upColor: col.up, downColor: col.down, wickUpColor: col.up, wickDownColor: col.down, borderVisible: false })
      : p.chartType === "bars" ? chart.addSeries(BarSeries, { upColor: col.up, downColor: col.down })
      : p.chartType === "line" ? chart.addSeries(LineSeries, { color: col.acc, lineWidth: 2 })
      : chart.addSeries(AreaSeries, { lineColor: col.acc, topColor: col.acc + "55", bottomColor: col.acc + "00", lineWidth: 2 });
    s.setData((p.chartType === "line" || p.chartType === "area" ? data.map((b) => ({ time: b.time as UTCTimestamp, value: b.close })) : data.map((b) => ({ ...b, time: b.time as UTCTimestamp }))) as any);
    if (data.length && trades.length) {
      const t0 = data[0].time, t1 = data[data.length - 1].time;
      const mk: SeriesMarker<Time>[] = [];
      for (const t of trades) {
        if (t.entry_ts >= t0 && t.entry_ts <= t1) mk.push({ time: t.entry_ts as UTCTimestamp, position: t.dir === 1 ? "belowBar" : "aboveBar",
          shape: t.dir === 1 ? "arrowUp" : "arrowDown", color: t.dir === 1 ? col.up : col.down, text: t.dir === 1 ? "L" : "S" });
        if (t.exit_ts >= t0 && t.exit_ts <= t1) mk.push({ time: t.exit_ts as UTCTimestamp, position: "inBar", shape: "circle",
          color: t.pnl >= 0 ? col.up : col.down, text: `${t.pnl >= 0 ? "+" : ""}${fmtN(t.r ?? t.pnl, 1)}${t.r != null ? "R" : ""}` });
      }
      createSeriesMarkers(s, mk.sort((a, b) => (a.time as number) - (b.time as number)));
    }
    const last = data[data.length - 1];
    setLeg(last ?? null);
    chart.subscribeCrosshairMove((e) => {
      const d = e.time != null ? data.find((b) => b.time === e.time) : null;
      setLeg(d ?? last ?? null);
    });
  });
  return (
    <div className="tv" style={{ height }}>
      {leg && <div className="legend">
        <span>{unit} · UTC</span>
        <span>O <b>{fmtN(leg.open, 5)}</b></span><span>H <b>{fmtN(leg.high, 5)}</b></span>
        <span>B <b>{fmtN(leg.low, 5)}</b></span><span>C <b className={leg.close >= leg.open ? "u" : "d"}>{fmtN(leg.close, 5)}</b></span>
        <span>{utcS(leg.time)}</span>
      </div>}
      <div ref={ref} style={{ height }} />
    </div>
  );
}

/** Capital (au-dessus / en dessous du capital initial) + volet « sous l'eau » (drawdown en % du pic). */
export function EquityChart({ trades, initial, height = 360 }: { trades: Trade[]; initial: number; height?: number }) {
  const [leg, setLeg] = useState<{ t: number; eq: number; dd: number } | null>(null);
  const pts = useMemo(() => {
    let eq = initial, peak = initial;
    const out = trades.slice().sort((a, b) => a.exit_ts - b.exit_ts).map((t) => {
      eq += t.pnl; peak = Math.max(peak, eq);
      return { time: t.exit_ts, eq, dd: peak > 0 ? ((eq - peak) / peak) * 100 : 0 };
    });
    return clean(out);
  }, [trades, initial]);
  const ref = useTvChart(height, [pts], (chart, col) => {
    const s = chart.addSeries(BaselineSeries, {
      baseValue: { type: "price", price: initial }, lineWidth: 2,
      topLineColor: col.up, topFillColor1: col.up + "44", topFillColor2: col.up + "05",
      bottomLineColor: col.down, bottomFillColor1: col.down + "05", bottomFillColor2: col.down + "44",
    });
    s.setData(pts.map((x) => ({ time: x.time as UTCTimestamp, value: x.eq })));
    s.createPriceLine({ price: initial, color: col.mut, lineStyle: LineStyle.Dotted, lineWidth: 1, axisLabelVisible: true, title: "initial" });
    const dd = chart.addSeries(HistogramSeries, { color: col.down + "aa", priceFormat: { type: "custom", formatter: (v: number) => fmtN(v, 1) + " %" } }, 1);
    dd.setData(pts.map((x) => ({ time: x.time as UTCTimestamp, value: x.dd })));
    chart.panes()[1]?.setStretchFactor(0.35);
    const last = pts[pts.length - 1];
    setLeg(last ? { t: last.time, eq: last.eq, dd: last.dd } : null);
    chart.subscribeCrosshairMove((e) => {
      const x = e.time != null ? pts.find((q) => q.time === e.time) : null;
      setLeg(x ? { t: x.time, eq: x.eq, dd: x.dd } : last ? { t: last.time, eq: last.eq, dd: last.dd } : null);
    });
  });
  if (!pts.length) return <Empty text="Aucune transaction à tracer." />;
  return (
    <div className="tv" style={{ height }}>
      {leg && <div className="legend">
        <span>capital <b className={leg.eq >= initial ? "u" : "d"}>{fmtN(leg.eq, 2)}</b></span>
        <span>sous le pic <b className="d">{fmtN(leg.dd, 2)} %</b></span><span>{utcS(leg.t)} UTC</span>
      </div>}
      <div ref={ref} style={{ height }} />
    </div>
  );
}

/** Plusieurs courbes temporelles (ex. convergence par tribu). */
export function SeriesChart({ series, height = 260, unit }: { series: { name: string; color?: string; pts: { time: number; value: number }[] }[]; height?: number; unit: string }) {
  const ref = useTvChart(height, [series], (chart, col) => {
    const pal = [col.acc, col.acc2, col.warn, col.up, col.down];
    series.forEach((s, i) => {
      const l = chart.addSeries(LineSeries, { color: s.color ?? pal[i % pal.length], lineWidth: 2, title: s.name, lineType: 1 });
      l.setData(clean(s.pts, (p) => Number.isFinite(p.value)).map((p) => ({ time: p.time as UTCTimestamp, value: p.value })));
    });
  });
  if (!series.some((s) => s.pts.length)) return <Empty text="Pas encore de points." />;
  return <div className="tv" style={{ height }}><div className="legend"><span>{unit} · UTC</span></div><div ref={ref} style={{ height }} /></div>;
}

// ---------------------------------------------------------------- SVG explicatifs
/** Largeur réelle du conteneur : les SVG sont dessinés en pixels, le texte garde sa taille sur toute largeur. */
function useW(): [(el: HTMLDivElement | null) => void, number] {
  const [w, setW] = useState(800);
  const obs = useRef<ResizeObserver | null>(null);
  // ref de rappel : suit l'élément même quand le rendu passe de « vide » à « graphique »
  const ref = useCallback((el: HTMLDivElement | null) => {
    obs.current?.disconnect();
    if (!el) return;
    obs.current = new ResizeObserver((e) => setW(Math.max(260, Math.floor(e[0].contentRect.width))));
    obs.current.observe(el);
  }, []);
  return [ref, w];
}

function useTip() {
  const [t, setT] = useState<{ x: number; y: number; s: string } | null>(null);
  const on = (s: string) => ({ onMouseMove: (e: React.MouseEvent) => setT({ x: e.clientX + 14, y: e.clientY + 14, s }), onMouseLeave: () => setT(null) });
  const view = t ? <div className="tip" style={{ left: Math.min(t.x, window.innerWidth - 330), top: t.y }}>{t.s}</div> : null;
  return { on, view };
}

export function Empty({ text }: { text: string }) {
  return <div className="empty"><Icon n="empty" s={28} /><span>{text}</span></div>;
}

/** Barres verticales autour de zéro (vert au-dessus, rouge en dessous), ligne de référence optionnelle. */
export function Bars({ items, unit, height = 200, refLine, refLabel }: {
  items: { label: string; value: number | null; tip?: string; muted?: boolean }[]; unit: string; height?: number; refLine?: number; refLabel?: string;
}) {
  const tip = useTip();
  const [box, W] = useW();
  const vals = items.map((i) => i.value).filter((v): v is number => v != null && Number.isFinite(v));
  if (!vals.length) return <div ref={box}><Empty text="Aucune valeur calculable." /></div>;
  const H = height, L = 52, B = 26, T = 10;
  const lo = Math.min(0, ...vals, refLine ?? 0), hi = Math.max(0, ...vals, refLine ?? 0) || 1;
  const Y = (v: number) => T + (hi - v) / (hi - lo || 1) * (H - T - B);
  const bw = (W - L - 8) / items.length;
  return (
    <div ref={box}>
      <svg className="viz" viewBox={`0 0 ${W} ${H}`} role="img" aria-label={`Barres (${unit})`}>
        {[hi, (hi + lo) / 2, lo].map((v, i) => <g key={i}><line className="gridl" x1={L} x2={W} y1={Y(v)} y2={Y(v)} /><text x={L - 6} y={Y(v) + 4} textAnchor="end">{fmtN(v, 1)}</text></g>)}
        <line className="axis" x1={L} x2={W} y1={Y(0)} y2={Y(0)} />
        {refLine != null && <><line className="ref" x1={L} x2={W} y1={Y(refLine)} y2={Y(refLine)} /><text x={W - 4} y={Y(refLine) - 4} textAnchor="end" style={{ fill: "var(--warn)" }}>{refLabel}</text></>}
        {items.map((it, i) => {
          const v = it.value;
          const x = L + i * bw + bw * 0.15, w = Math.max(1, bw * 0.7);
          const ok = v != null && Number.isFinite(v);
          return <g key={i} {...tip.on(`${it.label}\n${ok ? fmtN(v, 2) + " " + unit : "non calculable"}${it.tip ? "\n" + it.tip : ""}`)}>
            <rect className="hit" x={L + i * bw} y={T} width={bw} height={H - T - B} />
            {ok && <rect className={it.muted ? "muted" : v! >= 0 ? "up" : "down"} x={x} width={w} y={Math.min(Y(v!), Y(0))} height={Math.max(1, Math.abs(Y(v!) - Y(0)))} rx={2} />}
            {(i % Math.max(1, Math.ceil(items.length * 64 / (W - L))) === 0) && <text x={x + w / 2} y={H - 8} textAnchor="middle">{it.label}</text>}
          </g>;
        })}
      </svg>
      {tip.view}
    </div>
  );
}

/** Histogramme d'une distribution, avec repères (zéro, moyenne…). */
export function Histogram({ values, unit, bins = 24, marks = [], height = 200 }: { values: number[]; unit: string; bins?: number; marks?: { v: number; label: string }[]; height?: number }) {
  const tip = useTip();
  const [box, W] = useW();
  const v = values.filter(Number.isFinite);
  if (v.length < 2) return <div ref={box}><Empty text="Pas assez de valeurs pour une distribution." /></div>;
  const lo = Math.min(...v), hi = Math.max(...v) === lo ? lo + 1 : Math.max(...v);
  const n = Math.min(bins, Math.max(5, Math.ceil(Math.sqrt(v.length) * 2)));
  const step = (hi - lo) / n;
  const cnt = Array(n).fill(0);
  for (const x of v) cnt[Math.min(n - 1, Math.floor((x - lo) / step))]++;
  const H = height, L = 40, B = 26, T = 14, top = Math.max(...cnt);
  const X = (x: number) => L + (x - lo) / (hi - lo) * (W - L - 8);
  const Y = (c: number) => H - B - c / top * (H - T - B);
  return (
    <div ref={box}>
      <svg className="viz" viewBox={`0 0 ${W} ${H}`} role="img" aria-label={`Distribution (${unit})`}>
        <line className="axis" x1={L} x2={W} y1={H - B} y2={H - B} />
        <text x={L - 6} y={Y(top) + 4} textAnchor="end">{top}</text><text x={L - 6} y={H - B} textAnchor="end">0</text>
        {cnt.map((c, i) => {
          const a = lo + i * step, b = a + step;
          return <g key={i} {...tip.on(`${fmtN(a, 2)} → ${fmtN(b, 2)} ${unit}\n${c} valeur(s) · ${fmtN(c / v.length * 100, 1)} %`)}>
            <rect className="hit" x={X(a)} y={T} width={X(b) - X(a)} height={H - T - B} />
            <rect className={b <= 0 ? "down" : a >= 0 ? "up" : "muted"} x={X(a) + 1} y={Y(c)} width={Math.max(1, X(b) - X(a) - 2)} height={H - B - Y(c)} rx={2} opacity={0.85} />
          </g>;
        })}
        <text x={L} y={H - 8}>{fmtN(lo, 2)}</text><text x={W - 4} y={H - 8} textAnchor="end">{fmtN(hi, 2)} {unit}</text>
        {marks.filter((m) => m.v >= lo && m.v <= hi).map((m, i) => <g key={i}><line className="ref" x1={X(m.v)} x2={X(m.v)} y1={T - 4} y2={H - B} />
          <text x={X(m.v) + 4} y={T + 6 + i * 13} style={{ fill: "var(--warn)" }}>{m.label}</text></g>)}
      </svg>
      {tip.view}
    </div>
  );
}

/** Intervalles p5–p95 avec médiane, valeur observée et seuil : « où se situe la stratégie dans le hasard ». */
export function Ranges({ rows, height }: { rows: { label: string; p5: number; p50: number; p95: number; actual?: number | null; thr?: number | null; unit: string; goodHigh?: boolean }[]; height?: number }) {
  const tip = useTip();
  const [box, W] = useW();
  const H = height ?? rows.length * 46 + 10, L = Math.min(190, W * 0.3), R = 20;
  return (
    <div ref={box}>
      <svg className="viz" viewBox={`0 0 ${W} ${H}`} role="img" aria-label="Intervalles de Monte Carlo">
        {rows.map((r, i) => {
          const xs = [r.p5, r.p95, r.actual, r.thr].filter((x): x is number => x != null && Number.isFinite(x));
          const lo = Math.min(...xs), hi = Math.max(...xs) === lo ? lo + 1 : Math.max(...xs), pad = (hi - lo) * 0.08;
          const X = (v: number) => L + (v - lo + pad) / (hi - lo + 2 * pad) * (W - L - R);
          const y = 18 + i * 46;
          return <g key={i} {...tip.on(`${r.label}\np5 ${fmtN(r.p5)} · médiane ${fmtN(r.p50)} · p95 ${fmtN(r.p95)} ${r.unit}${r.actual != null ? `\nobservé ${fmtN(r.actual)}` : ""}${r.thr != null ? `\nseuil ${fmtN(r.thr)}` : ""}`)}>
            <rect className="hit" x={0} y={y - 16} width={W} height={40} />
            <text x={0} y={y + 4} className="t-fg">{r.label}</text>
            <text x={0} y={y + 18}>{r.unit}</text>
            <line className="gridl" x1={L} x2={W - R} y1={y} y2={y} strokeWidth={10} strokeLinecap="round" />
            <line x1={X(r.p5)} x2={X(r.p95)} y1={y} y2={y} stroke="var(--acc2)" strokeOpacity={0.55} strokeWidth={10} strokeLinecap="round" />
            <rect x={X(r.p50) - 1.5} y={y - 9} width={3} height={18} className="acc" />
            <text x={X(r.p5)} y={y + 22} textAnchor="middle">{fmtN(r.p5, 1)}</text>
            <text x={X(r.p95)} y={y + 22} textAnchor="middle">{fmtN(r.p95, 1)}</text>
            {r.thr != null && <><line className="ref" x1={X(r.thr)} x2={X(r.thr)} y1={y - 14} y2={y + 12} /><text x={X(r.thr) + 3} y={y - 8} style={{ fill: "var(--warn)" }}>seuil</text></>}
            {r.actual != null && <circle cx={X(r.actual)} cy={y} r={5} style={{ fill: "var(--fg)", stroke: "var(--panel)", strokeWidth: 2 }} />}
          </g>;
        })}
      </svg>
      {tip.view}
    </div>
  );
}

/** Carte de chaleur (corrélations, PnL heure × jour). Divergente autour de zéro. */
export function Heatmap({ rows, cols, get, unit, fmtv = (v) => fmtN(v, 2), max, pos = "var(--up)", neg = "var(--down)" }: {
  rows: string[]; cols: string[]; get: (r: number, c: number) => number | null; unit: string; fmtv?: (v: number) => string; max?: number; pos?: string; neg?: string;
}) {
  const tip = useTip();
  const [box, BW] = useW();
  const all: number[] = [];
  rows.forEach((_, r) => cols.forEach((_, c) => { const v = get(r, c); if (v != null && Number.isFinite(v)) all.push(Math.abs(v)); }));
  const m = max ?? (Math.max(0, ...all) || 1);
  const L = Math.min(120, 8 + Math.max(...rows.map((x) => x.length)) * 7), T = 22, cw = Math.max(14, (BW - L) / cols.length), ch = 24;
  const W = L + cw * cols.length, H = T + ch * rows.length;
  return (
    <div ref={box}>
      <svg className="viz" viewBox={`0 0 ${W} ${H}`} role="img" aria-label={`Carte de chaleur (${unit})`}>
        {cols.map((c, j) => <text key={j} x={L + j * cw + cw / 2} y={14} textAnchor="middle">{c}</text>)}
        {rows.map((rl, i) => <g key={i}>
          <text x={L - 6} y={T + i * ch + ch / 2 + 4} textAnchor="end">{rl}</text>
          {cols.map((cl, j) => {
            const v = get(i, j);
            const ok = v != null && Number.isFinite(v);
            const pct = ok ? Math.min(100, Math.abs(v!) / m * 85 + (v === 0 ? 0 : 10)) : 0;
            const fill = !ok ? "var(--grid)" : `color-mix(in srgb, ${v! >= 0 ? pos : neg} ${pct}%, var(--panel2))`;
            return <g key={j} {...tip.on(`${rl} · ${cl}\n${ok ? fmtv(v!) + " " + unit : "aucune donnée"}`)}>
              <rect x={L + j * cw + 1} y={T + i * ch + 1} width={cw - 2} height={ch - 2} rx={3} style={{ fill }} />
              {cw >= 46 && ok && <text x={L + j * cw + cw / 2} y={T + i * ch + ch / 2 + 4} textAnchor="middle" className="t-fg">{fmtv(v!)}</text>}
            </g>;
          })}
        </g>)}
      </svg>
      {tip.view}
    </div>
  );
}

/** Nuage de points (front de Pareto) ; clic = ouvrir la révision. */
export function Scatter({ pts, xl, yl, onPick, highlight, height = 380 }: {
  pts: { x: number; y: number; id: string; front?: boolean }[]; xl: string; yl: string; onPick?: (id: string) => void; highlight?: string; height?: number;
}) {
  const tip = useTip();
  const [box, W] = useW();
  const ok = pts.filter((p) => Number.isFinite(p.x) && Number.isFinite(p.y));
  if (!ok.length) return <div ref={box}><Empty text="Aucun point calculable." /></div>;
  const H = height, L = 56, B = 34, T = 12;
  const xs = ok.map((p) => p.x), ys = ok.map((p) => p.y);
  const [x0, x1] = [Math.min(...xs), Math.max(...xs) === Math.min(...xs) ? Math.min(...xs) + 1 : Math.max(...xs)];
  const [y0, y1] = [Math.min(...ys), Math.max(...ys) === Math.min(...ys) ? Math.min(...ys) + 1 : Math.max(...ys)];
  const X = (v: number) => L + (v - x0) / (x1 - x0) * (W - L - 10), Y = (v: number) => H - B - (v - y0) / (y1 - y0) * (H - T - B);
  const ticks = (a: number, b: number) => [0, 0.25, 0.5, 0.75, 1].map((k) => a + (b - a) * k);
  return (
    <div ref={box}>
      <svg className="viz" viewBox={`0 0 ${W} ${H}`} role="img" aria-label={`${yl} en fonction de ${xl}`}>
        {ticks(y0, y1).map((v, i) => <g key={"y" + i}><line className="gridl" x1={L} x2={W} y1={Y(v)} y2={Y(v)} /><text x={L - 6} y={Y(v) + 4} textAnchor="end">{fmtN(v, 2)}</text></g>)}
        {ticks(x0, x1).map((v, i) => <g key={"x" + i}><line className="gridl" x1={X(v)} x2={X(v)} y1={T} y2={H - B} /><text x={X(v)} y={H - B + 14} textAnchor="middle">{fmtN(v, 2)}</text></g>)}
        <text x={W - 4} y={H - 4} textAnchor="end" className="t-fg">{xl} →</text>
        <text x={L + 4} y={T + 10} className="t-fg">↑ {yl}</text>
        {ok.filter((p) => !p.front).concat(ok.filter((p) => p.front)).map((p) => (
          <circle key={p.id} cx={X(p.x)} cy={Y(p.y)} r={p.id === highlight ? 7 : p.front ? 5 : 3.2}
            className={"pt" + (p.front ? " front" : "") + (p.id === highlight ? " hl" : "")} onClick={() => onPick?.(p.id)}
            {...tip.on(`${p.id}\n${xl} ${fmtN(p.x)} · ${yl} ${fmtN(p.y)}${p.front ? "\nretenu (statut ≥ filtrée)" : ""}`)} />))}
      </svg>
      {tip.view}
    </div>
  );
}

/** Courbes sur axe numérique (ex. génération), plusieurs séries, survol = valeurs de toutes les séries. */
export function Lines({ series, xl, unit, height = 240 }: { series: { name: string; pts: { x: number; y: number }[] }[]; xl: string; unit: string; height?: number }) {
  const [hx, setHx] = useState<number | null>(null);
  const [box, W] = useW();
  const all = series.flatMap((s) => s.pts).filter((p) => Number.isFinite(p.x) && Number.isFinite(p.y));
  if (!all.length) return <div ref={box}><Empty text="Pas encore de points." /></div>;
  const H = height, L = 52, B = 28, T = 12;
  const x0 = Math.min(...all.map((p) => p.x)), x1 = Math.max(...all.map((p) => p.x)) === x0 ? x0 + 1 : Math.max(...all.map((p) => p.x));
  const y0 = Math.min(...all.map((p) => p.y)), y1 = Math.max(...all.map((p) => p.y)) === y0 ? y0 + 1 : Math.max(...all.map((p) => p.y));
  const X = (v: number) => L + (v - x0) / (x1 - x0) * (W - L - 10), Y = (v: number) => H - B - (v - y0) / (y1 - y0) * (H - T - B);
  const pal = ["var(--acc)", "var(--acc2)", "var(--warn)", "var(--up)", "var(--down)"];
  const near = (s: { pts: { x: number; y: number }[] }) => hx == null ? null : s.pts.reduce<{ x: number; y: number } | null>((a, p) => (a == null || Math.abs(p.x - hx) < Math.abs(a.x - hx) ? p : a), null);
  return (
    <div ref={box} style={{ position: "relative" }}>
      <svg className="viz" viewBox={`0 0 ${W} ${H}`} role="img" aria-label={`${unit} selon ${xl}`}
        onMouseMove={(e) => { const r = (e.currentTarget as SVGSVGElement).getBoundingClientRect(); setHx(x0 + ((e.clientX - r.left) / r.width * W - L) / (W - L - 10) * (x1 - x0)); }}
        onMouseLeave={() => setHx(null)}>
        {[y0, (y0 + y1) / 2, y1].map((v, i) => <g key={i}><line className="gridl" x1={L} x2={W} y1={Y(v)} y2={Y(v)} /><text x={L - 6} y={Y(v) + 4} textAnchor="end">{fmtN(v, 2)}</text></g>)}
        <text x={L} y={H - 8}>{fmtN(x0, 0)}</text><text x={W - 4} y={H - 8} textAnchor="end">{xl} {fmtN(x1, 0)} →</text>
        {series.map((s, i) => {
          const pts = s.pts.filter((p) => Number.isFinite(p.y)).sort((a, b) => a.x - b.x);
          return <path key={i} d={pts.map((p, k) => `${k ? "L" : "M"}${X(p.x).toFixed(1)},${Y(p.y).toFixed(1)}`).join("")} fill="none" style={{ stroke: pal[i % pal.length] }} strokeWidth={2} />;
        })}
        {hx != null && <line className="axis" x1={X(Math.max(x0, Math.min(x1, hx)))} x2={X(Math.max(x0, Math.min(x1, hx)))} y1={T} y2={H - B} strokeDasharray="3 3" />}
        {hx != null && series.map((s, i) => { const p = near(s); return p && <circle key={i} cx={X(p.x)} cy={Y(p.y)} r={4} style={{ fill: pal[i % pal.length] }} />; })}
      </svg>
      <div className="row" style={{ gap: 14, marginTop: 4 }}>
        {series.map((s, i) => { const p = near(s) ?? s.pts[s.pts.length - 1]; return (
          <span key={i} className="muted" style={{ display: "inline-flex", gap: 6, alignItems: "center", fontFamily: "var(--font-num)", fontSize: 11 }}>
            <i style={{ width: 12, height: 3, background: pal[i % pal.length], display: "inline-block", borderRadius: 2 }} />{s.name}
            {p && <b style={{ color: "var(--fg)" }}>{fmtN(p.y, 3)}</b>}{p && <span>({xl} {fmtN(p.x, 0)})</span>}</span>); })}
      </div>
    </div>
  );
}

/** Barres horizontales empilées (poids, répartition). */
export function Stack({ parts, unit = "%" }: { parts: { label: string; value: number }[]; unit?: string }) {
  const tip = useTip();
  const tot = parts.reduce((a, p) => a + Math.max(0, p.value), 0) || 1;
  const pal = ["var(--acc)", "var(--acc2)", "var(--warn)", "var(--up)", "var(--down)", "var(--mut)"];
  return (
    <div>
      <div style={{ display: "flex", height: 14, borderRadius: 7, overflow: "hidden", background: "var(--grid)" }}>
        {parts.map((p, i) => <div key={i} style={{ width: `${Math.max(0, p.value) / tot * 100}%`, background: pal[i % pal.length] }} {...tip.on(`${p.label}\n${fmtN(p.value, 1)} ${unit}`)} />)}
      </div>
      <div className="row" style={{ marginTop: 8, gap: 12 }}>
        {parts.map((p, i) => <span key={i} className="muted" style={{ display: "inline-flex", gap: 6, alignItems: "center" }}>
          <i style={{ width: 10, height: 10, borderRadius: 3, background: pal[i % pal.length], display: "inline-block" }} />{p.label} <b style={{ color: "var(--fg)", fontFamily: "var(--font-num)" }}>{fmtN(p.value, 1)} {unit}</b></span>)}
      </div>
      {tip.view}
    </div>
  );
}
