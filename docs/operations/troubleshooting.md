# Dépannage

| Symptôme | Cause probable | Action |
|---|---|---|
| « Le moteur scientifique n'a pas démarré » | uv absent du PATH ou environnement non synchronisé | `cd engine; uv sync`, puis relancer ; le journal du moteur est affiché à l'écran |
| Import MT5 : « profil de fuseau incohérent » | le fuseau déclaré ne correspond pas à l'heure serveur observée | choisir le bon profil (`NY+7`, `UTC+2`…), ne pas forcer |
| Import MT5 : « initialisation MT5 impossible » | terminal non installé/non connecté | ouvrir MT5 une fois, se connecter au compte démo, réessayer |
| Campagne refusée : « spread historique inconnu » | barres à spread nul dans le dataset | renseigner un spread plancher (hypothèse documentée) |
| Parité « bloquée : terminal MT5 ouvert » | le testeur CLI exige un terminal fermé | fermer MT5, relancer la vérification |
| Compilation « échec » | voir le journal MetaEditor (artefact `compile_log`) | le diagnostic liste les lignes d'erreur |
| Parité « aucune trace produite » | EA non lancé par le testeur (symbole/période) | consulter `<données MT5>\Tester\logs` et `MQL5\Experts\QLab\<run>.ini` |
| Tâche bloquée en « paused » après un crash | reprise sécurisée au démarrage | Tâches → « Reprendre » : repart du dernier checkpoint sans dupliquer les évaluations |
| Écran vide dans l'interface | renderer en erreur | lancer en mode QA : `QLAB_UI_SNAPSHOT_DIR=<dossier>` produit des captures et `renderer-log.txt` |
| Scripts Python lancés à la main créent plusieurs campagnes | absence de `if __name__ == "__main__":` (multiprocessing Windows) | toujours protéger le point d'entrée ; l'API est déjà protégée |
