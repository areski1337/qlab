# Installation et premier démarrage (Windows)

## Prérequis
| Outil | Version testée | Rôle |
|---|---|---|
| Windows | 11 (build 26300) | |
| uv | 0.13.0 | installe Python 3.13 et les dépendances du moteur |
| Node.js / npm | 24.20 / 11.19 | build de l'interface |
| MetaTrader 5 | build 6254 | données, MetaEditor, Strategy Tester (facultatif pour la recherche sur données importées/synthétiques) |
Espace disque : ~1 Go (dépendances) + données (≈ 15 Mo par million de barres en Parquet zstd).

## Installation
```powershell
powershell -ExecutionPolicy Bypass -File scripts\install.ps1
```
Le script vérifie les outils, l'espace disque, synchronise l'environnement Python (`uv sync`), installe et construit l'interface (`npm ci`, `npm run build`), télécharge le binaire Electron officiel et lance le diagnostic de santé.

## Démarrage
```powershell
powershell -ExecutionPolicy Bypass -File scripts\start.ps1
```
Données par défaut : `%LOCALAPPDATA%\QLab` (modifiable : variable `QLAB_DATA_DIR`). L'interface lance le moteur, qui écoute sur `127.0.0.1` à un port aléatoire, protégé par un jeton généré à chaque démarrage.

## Configuration MT5
- Chemins par défaut : `C:\Program Files\MetaTrader 5\terminal64.exe` et `MetaEditor64.exe` (modifiables dans `settings.json` du répertoire de données).
- Le répertoire de données du terminal est détecté via `origin.txt`.
- L'import utilise le compte déjà connecté dans le terminal ; QLab ne stocke aucun mot de passe.
- Le Strategy Tester en ligne de commande nécessite que le terminal soit **fermé**.
- Les EA générés sont copiés dans `MQL5\Experts\QLab\` ; les traces et drapeaux dans `Common\Files\QLab\`.

## Premier démarrage conseillé
1. Données → « Dataset synthétique » (identifié SYNTHÉTIQUE) pour vérifier la chaîne.
2. Données → importer XAUUSD M5 + H1 depuis MT5 (fuseau `NY+7` vérifié contre l'heure serveur).
3. Campagnes → lancer une petite campagne (population 8, 2 générations) puis une campagne complète.
4. Génome → valider une révision du front ; MQL5 → vérification de parité (terminal fermé).

## Diagnostic de santé
Tableau de bord, ou `GET /api/v1/health` : intégrité SQLite, schéma, disque libre, présence de MT5/MetaEditor, worker.

## Désinstallation
Supprimer le dossier du projet. Les données restent dans `%LOCALAPPDATA%\QLab` (à supprimer manuellement si souhaité, après sauvegarde). Les EA copiés restent dans `MQL5\Experts\QLab\` du terminal.

## Mises à jour

1. Construire et publier une nouvelle version :
   `powershell -ExecutionPolicy Bypass -File scripts\build_installer.ps1 -Version 0.2.0 -Publish D:\QLab\updates -Notes "…"`
   Le dossier reçoit `QLab Setup 0.2.0.exe` puis `latest.json` (version, fichier, taille, SHA-512, date, notes).
   Pour une source https, servir ce dossier tel quel (http non chiffré refusé).
2. Dans QLab : Paramètres → « Mises à jour de l'application » → saisir la source (ou variable d'environnement
   `QLAB_UPDATE_SOURCE`, prioritaire) → Vérifier → Télécharger → Installer et redémarrer.
3. QLab vérifie la source 15 s après le démarrage et affiche « Mise à jour x.y.z disponible » dans la barre
   d'état ; rien n'est téléchargé ni installé sans action.

Garanties : l'installateur n'est exécuté que si sa taille et son SHA-512 correspondent au manifeste ; les données
(`%APPDATA%\QLab` et le répertoire de données) ne sont pas touchées ; les migrations de base s'appliquent au
redémarrage du moteur après sauvegarde automatique ; les tâches en cours repassent en pause et se reprennent.
Limite : sans signature de code, l'authenticité repose sur la confiance dans la source (dossier maîtrisé ou https).

