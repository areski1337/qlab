import React from "react";
import { Incomplete } from "../ui";

export function Portfolio() {
  return (
    <div>
      <h1>Portefeuilles & exposition</h1>
      <Incomplete what="optimisation de portefeuille" why="Le moteur de portefeuille (corrélations, drawdown simultané, allocation bornée) n'est pas encore implémenté dans cette version." />
    </div>
  );
}

export function Demo() {
  return (
    <div>
      <h1>Surveillance du compte démo</h1>
      <Incomplete what="surveillance démo" why="La lecture des positions/transactions du compte démo et la détection de dégradation ne sont pas encore implémentées dans cette version." />
    </div>
  );
}
