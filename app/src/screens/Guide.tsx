import React from "react";
import { fmt, PageHead, useApi } from "../ui";
import { useNav } from "../main";
import { LADDER } from "./Dashboard";

/** Parcours guidé : chaque étape est cochée d'après l'état réel (données, campagnes, statuts, déploiements). */
export function Guide() {
  const { go } = useNav();
  const h = useApi<any>("/health", [], true);
  const ds = useApi<any[]>("/datasets", [], true);
  const camps = useApi<any[]>("/campaigns", [], true);
  const st = useApi<any>("/stats", [], true);
  const demo = useApi<any>("/demo", [], true);
  const by: Record<string, number> = st.data?.revisions_by_status ?? {};
  const atLeast = (k: string) => LADDER.slice(LADDER.indexOf(k)).reduce((a, x) => a + (by[x] ?? 0), 0);
  const real = ds.data?.filter((d) => !d.synthetic) ?? [];
  const done = camps.data?.filter((c) => c.task_state === "completed") ?? [];
  const running = camps.data?.some((c) => ["queued", "running", "validating"].includes(c.task_state));
  const steps: { t: string; ok: boolean | null; now: string; todo: string; go: string; btn: string }[] = [
    { t: "MetaTrader 5 détecté", ok: h.data ? !!(h.data.mt5.terminal_found && h.data.mt5.metaeditor_found) : null,
      now: "terminal et MetaEditor trouvés", todo: "installer MT5 ou corriger les chemins dans la configuration", go: "settings", btn: "Paramètres" },
    { t: "Historique importé", ok: ds.data ? real.length > 0 : null,
      now: `${real.length} dataset(s) réel(s)`, todo: "importer un instrument depuis MT5 (ex. XAUUSD M15 + H1 pour le contexte)", go: "data", btn: "Importer" },
    { t: "Campagne terminée", ok: camps.data ? done.length > 0 : null,
      now: `${done.length} campagne(s) terminée(s)`, todo: running ? "une campagne est en cours : suivre sa progression" : "lancer une campagne (préréglage Standard, validation automatique activée)", go: running ? "lab" : "campaigns", btn: running ? "Laboratoire" : "Nouvelle campagne" },
    { t: "Stratégie robuste et validée hors échantillon", ok: st.data ? atLeast("oos_evaluated") > 0 : null,
      now: `${atLeast("oos_evaluated")} stratégie(s) au statut ≥ « évaluée hors échantillon »`, todo: "valider les meilleures stratégies (automatique en fin de campagne si activé, sinon depuis Génome)", go: "library", btn: "Bibliothèque" },
    { t: "EA compilé et concordant avec MT5", ok: st.data ? atLeast("mt5_validated") > 0 : null,
      now: `${atLeast("mt5_validated")} stratégie(s) validée(s) MT5`, todo: "générer l'EA et vérifier la parité au Strategy Tester (MT5 fermé)", go: "mt5", btn: "MQL5 & MT5" },
    { t: "Observation en compte démo", ok: demo.data ? (demo.data.deployments?.length ?? 0) > 0 : null,
      now: `${demo.data?.deployments?.length ?? 0} déploiement(s) démo`, todo: "enregistrer un déploiement démo et attacher l'EA dans MT5 (vous seul activez l'AutoTrading)", go: "demo", btn: "Démo" },
  ];
  const next = steps.findIndex((s) => !s.ok);  // première étape non franchie (ou encore en vérification)
  return (
    <div>
      <PageHead title="Guide" sub="De l'installation à l'observation en démo : où vous en êtes et quoi faire ensuite. Aucune étape ne passe d'ordre réel." />
      <div className="card">
        <ol className="guide">
          {steps.map((s, i) => (
            <li key={s.t} className={s.ok ? "ok" : i === next && s.ok === false ? "next" : ""}>
              <span className="mark" aria-hidden="true">{s.ok ? "✓" : i + 1}</span>
              <div className="body">
                <b>{s.t}</b>
                <div className="muted">{s.ok == null ? "vérification…" : s.ok ? s.now : s.todo}</div>
              </div>
              {(!s.ok || i === steps.length - 1) && <button className={"btn" + (i === next ? " primary" : "")} onClick={() => go({ screen: s.go })}>{s.btn}</button>}
            </li>))}
        </ol>
        <p className="muted" style={{ marginTop: 10 }}>{next < 0 ? "Toutes les étapes sont franchies : surveiller la démo et comparer au backtest." :
          `Prochaine étape : ${steps[next].t.toLowerCase()}. Progression ${fmt(steps.filter((s) => s.ok).length, 0)}/${steps.length}.`}</p>
      </div>
    </div>
  );
}
