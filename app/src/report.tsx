// Rapport de performance d'une évaluation : toutes les métriques calculées par le moteur (metrics/core.py), avec leur
// définition exacte, les hypothèses de coûts utilisées et des statistiques dérivées des transactions conservées.
import React, { useMemo } from "react";
import { Card, fmt, utc } from "./ui";
import { Bars, Explain, Scatter, Trade } from "./charts";

type Row = [string, string, (m: any) => React.ReactNode, string];
const pct = (x: any, d = 1) => (x == null ? "—" : `${fmt(x * 100, d)} %`);

// [clé, libellé, valeur, définition] — définitions alignées sur metrics/core.py
const GROUPS: [string, Row[]][] = [
  ["Rendement", [
    ["net_profit", "Profit net", (m) => fmt(m.net_profit, 2), "Somme des PnL nets des trades clôturés (commission, swap et spread inclus), devise du compte."],
    ["return_pct", "Rendement", (m) => `${fmt(m.return_pct, 2)} %`, "Profit net / capital initial."],
    ["expectancy", "Espérance / trade", (m) => fmt(m.expectancy, 2), "PnL net moyen par trade, devise du compte."],
    ["expectancy_r", "Espérance (R)", (m) => fmt(m.expectancy_r, 3), "Moyenne des R par trade ; R = résultat de prix (spread et glissement inclus dans les prix d'exécution) / risque initial (distance au stop × valeur du point × lots). Avant commission et swap."],
    ["profit_factor", "Profit factor", (m) => fmt(m.profit_factor, 2), "Somme des gains nets / somme des pertes nettes. Vide si aucune perte."],
    ["positive_months_ratio", "Mois positifs", (m) => pct(m.positive_months_ratio, 0), "Part des mois (ayant au moins une clôture) dont le PnL net est positif."],
    ["trades_per_month", "Trades / mois", (m) => fmt(m.trades_per_month, 1), "Nombre de trades / durée de la fenêtre évaluée (mois de 30,44 jours)."],
  ]],
  ["Risque", [
    ["max_dd_pct", "Drawdown max", (m) => `${fmt(m.max_dd_pct, 2)} %`, "Plus forte baisse du capital depuis un sommet, mesurée sur le capital de clôture des trades (la perte latente intra-trade n'est pas comptée)."],
    ["max_dd_abs", "Drawdown max (montant)", (m) => fmt(m.max_dd_abs, 2), "Même mesure en devise du compte."],
    ["max_dd_at", "Fond du drawdown", (m) => utc(m.max_dd_at), "Clôture du trade au fond du drawdown maximal."],
    ["longest_underwater_days", "Plus longue période sous l'eau", (m) => `${fmt(m.longest_underwater_days, 0)} j`, "Jours ouvrés consécutifs sous le dernier sommet du capital journalier."],
    ["sharpe", "Sharpe", (m) => fmt(m.sharpe, 2), "Moyenne / écart-type des rendements journaliers (jours ouvrés de la fenêtre, jours sans clôture = 0), × √252. Sans taux sans risque."],
    ["sortino", "Sortino", (m) => fmt(m.sortino, 2), "Comme le Sharpe, avec l'écart-type des seuls rendements journaliers négatifs."],
    ["r2_equity", "Régularité (R²)", (m) => fmt(m.r2_equity, 3), "R² d'une droite ajustée à la courbe de capital par trade, signé (négatif si perte nette)."],
    ["daily_returns_n", "Jours de l'échantillon", (m) => fmt(m.daily_returns_n, 0), "Nombre de rendements journaliers utilisés pour Sharpe/Sortino."],
  ]],
  ["Trades", [
    ["n_trades", "Trades", (m) => fmt(m.n_trades, 0), "Trades clôturés dans la fenêtre."],
    ["win_rate", "Taux de réussite", (m) => pct(m.win_rate), "Part des trades à PnL net strictement positif."],
    ["long_share", "Part long", (m) => pct(m.long_share, 0), "Part des trades acheteurs."],
    ["avg_bars_held", "Durée moyenne", (m) => `${fmt(m.avg_bars_held, 1)} barres`, "Barres entre l'entrée et la sortie (incluses)."],
    ["ambiguous_ratio", "Barres ambiguës", (m) => pct(m.ambiguous_ratio), "Part des trades dont la sortie s'est jouée sur une barre touchant stop et objectif : ordre intrabarre supposé (prudent, ou résolu en M1 si disponible)."],
  ]],
];

export function PerfReport({ ev, trades }: { ev: any; trades: Trade[] }) {
  const m = ev.metrics ?? {};
  const cp = ev.cost_profile;
  const d = useMemo(() => derive(trades), [trades]);
  const years = Object.entries(m.by_year ?? {}).sort(([a], [b]) => Number(a) - Number(b));
  const skipped = Object.entries(m.skipped ?? {}).filter(([, v]) => (v as number) > 0);
  return (
    <>
      <Card title={`Rapport détaillé · segment ${ev.segment}`} wide>
        <div className="report">
          {GROUPS.map(([g, rows]) => (
            <section key={g}>
              <h3>{g}</h3>
              <dl className="kv metrics">{rows.map(([k, l, f, def]) => (
                <React.Fragment key={k}><dt title={def}>{l}<span className="def">{def}</span></dt><dd className="num">{f(m)}</dd></React.Fragment>))}</dl>
            </section>))}
          <section>
            <h3>Coûts supportés</h3>
            <dl className="kv metrics">
              <dt>Spread (estimé)<span className="def">Coût du spread inclus dans les prix d'exécution, estimé par trade.</span></dt><dd className="num">{fmt(m.costs?.spread_est, 2)}</dd>
              <dt>Commission</dt><dd className="num">{fmt(m.costs?.commission, 2)}</dd>
              <dt>Swap</dt><dd className="num">{fmt(m.costs?.swap, 2)}</dd>
              <dt>Coûts / profit brut<span className="def">(spread + commission − swap reçu) / (profit net + ces coûts). Part de l'avantage absorbée par les coûts.</span></dt>
              <dd className="num">{costShare(m)}</dd>
            </dl>
            <h3>Hypothèses de coûts</h3>
            {cp ? <dl className="kv metrics">
              <dt>Spread</dt><dd>{cp.spread_mode === "max" ? `max(historique, ${cp.fixed_spread_points ?? "—"} pts)` : cp.spread_mode === "fixed" ? `fixe ${cp.fixed_spread_points} pts` : "historique"}{cp.spread_scale && cp.spread_scale !== 1 ? ` × ${cp.spread_scale}` : ""} <span className="muted">({cp.provenance?.spread ?? "?"})</span></dd>
              <dt>Commission</dt><dd>{fmt(cp.commission_per_lot_side, 2)} / lot / côté <span className="muted">({cp.provenance?.commission ?? "?"})</span></dd>
              <dt>Glissement</dt><dd>{fmt(cp.slippage_points, 0)} pts <span className="muted">({cp.provenance?.slippage ?? "?"})</span></dd>
              <dt>Swap</dt><dd>{cp.apply_swap ? "appliqué (spécification du symbole)" : "ignoré"}</dd>
            </dl> : <p className="muted">Profil non enregistré (évaluation antérieure à la version 0.7) : seule son empreinte est connue.</p>}
            {skipped.length > 0 && <><h3>Signaux non exécutés</h3><dl className="kv metrics">{skipped.map(([k, v]) => <React.Fragment key={k}><dt>{k}</dt><dd className="num">{fmt(v as number, 0)}</dd></React.Fragment>)}</dl></>}
            {m.halted && <div className="alert warn">Le contrôleur de risque a arrêté la simulation avant la fin de la fenêtre : {String(m.halted)}.</div>}
          </section>
          {d && <section>
            <h3>Séquences et répartition (transactions conservées)</h3>
            <dl className="kv metrics">
              <dt>Pertes consécutives max</dt><dd className="num">{d.maxLoss}</dd>
              <dt>Gains consécutifs max</dt><dd className="num">{d.maxWin}</dd>
              <dt>Gain moyen / perte moyenne<span className="def">Payoff : gain net moyen des trades gagnants / perte nette moyenne des perdants.</span></dt><dd className="num">{fmt(d.payoff, 2)}</dd>
              <dt>Plus gros gain</dt><dd className="num pos">{fmt(d.best, 2)}</dd>
              <dt>Plus grosse perte</dt><dd className="num neg">{fmt(d.worst, 2)}</dd>
              <dt>Part du profit des 5 meilleurs<span className="def">Somme des 5 meilleurs trades / profit net. Au-delà de 100 %, le reste des trades est perdant.</span></dt><dd className="num">{d.top5 == null ? "—" : `${fmt(d.top5 * 100, 0)} %`}</dd>
              <dt>MAE moyenne (R)<span className="def">Excursion adverse maximale pendant le trade, en R.</span></dt><dd className="num">{fmt(d.mae, 2)}</dd>
              <dt>MFE moyenne (R)<span className="def">Excursion favorable maximale pendant le trade, en R.</span></dt><dd className="num">{fmt(d.mfe, 2)}</dd>
            </dl>
          </section>}
        </div>
      </Card>
      {years.length > 0 && <Card title="Résultat par année">
        <Bars unit="profit net" items={years.map(([y, v]: any) => ({ label: y, value: v.net, tip: `${v.n} trades` }))} />
        <Explain>Un avantage concentré sur une ou deux années est plus fragile qu'un résultat réparti.</Explain>
      </Card>}
      {d && d.hasMae && <Card title="MAE / résultat par trade">
        <Scatter pts={trades.map((t: any, i) => ({ id: String(i), x: t.mae_r, y: t.r, front: (t.r ?? 0) > 0 }))} xl="MAE (R)" yl="résultat (R)" height={300} />
        <Explain>Chaque point est un trade : excursion adverse maximale (X) contre résultat final (Y). Des gagnants qui reculent rarement au-delà d'une certaine MAE indiquent un stop surdimensionné ; des perdants concentrés à −1 R, un stop qui travaille.</Explain>
      </Card>}
    </>
  );
}

function costShare(m: any) {
  const c = m.costs;
  if (!c || m.net_profit == null) return "—";
  const cost = (c.spread_est ?? 0) + (c.commission ?? 0) - (c.swap ?? 0);
  const gross = m.net_profit + cost;
  return gross > 0 ? `${fmt((cost / gross) * 100, 1)} %` : "n/a (brut ≤ 0)";
}

function derive(tr: any[]) {
  if (!tr.length) return null;
  let cw = 0, cl = 0, maxWin = 0, maxLoss = 0;
  const pnl = tr.slice().sort((a, b) => a.exit_ts - b.exit_ts).map((t) => t.pnl);
  for (const p of pnl) {
    if (p > 0) { cw++; cl = 0; } else { cl++; cw = 0; }
    maxWin = Math.max(maxWin, cw); maxLoss = Math.max(maxLoss, cl);
  }
  const wins = pnl.filter((p) => p > 0), losses = pnl.filter((p) => p <= 0);
  const avg = (a: number[]) => (a.length ? a.reduce((s, x) => s + x, 0) / a.length : null);
  const aw = avg(wins), al = avg(losses);
  const net = pnl.reduce((s, x) => s + x, 0);
  const top = [...pnl].sort((a, b) => b - a).slice(0, 5).reduce((s, x) => s + x, 0);
  const maes = tr.map((t) => t.mae_r).filter(Number.isFinite), mfes = tr.map((t) => t.mfe_r).filter(Number.isFinite);
  return { maxWin, maxLoss, payoff: aw != null && al ? aw / Math.abs(al) : null, best: Math.max(...pnl), worst: Math.min(...pnl),
    top5: net > 0 ? top / net : null, mae: avg(maes), mfe: avg(mfes), hasMae: maes.length > 0 };
}
