# Sauvegarde, restauration, migrations

## Sauvegarde
- Interface : Paramètres → « Sauvegarder maintenant », ou `POST /api/v1/backups`.
- Contenu : copie cohérente de la base (API backup SQLite, sûre pendant l'écriture), `artifacts/`, `datasets/`, `manifest.json` (SHA-256 de chaque fichier, versions des composants).
- Emplacement : `<données>/backups/qlab-backup-<horodatage UTC>.zip`.

## Vérifier une sauvegarde (sans risque)
Paramètres → « Vérifier » : restauration dans un répertoire temporaire puis contrôle des empreintes, `PRAGMA integrity_check`, clés étrangères, artefacts référencés, fichiers de datasets référencés. Rien n'est modifié.

## Restaurer
La restauration n'écrase jamais un répertoire non vide.
```powershell
cd engine
uv run python -c "from qlab.storage.backup import restore_backup; print(restore_backup(r'C:\chemin\qlab-backup-XXXX.zip', r'C:\QLabRestaure'))"
```
Si le rapport indique `"ok": true`, démarrer l'application sur ce répertoire (`$env:QLAB_DATA_DIR='C:\QLabRestaure'`), contrôler, puis le conserver comme répertoire principal. L'ancien répertoire reste intact pour retour arrière.

## Migrations
Au démarrage, les migrations manquantes (`engine/src/qlab/storage/migrations/NNNN_*.sql`) sont appliquées après : contrôle d'intégrité, contrôle d'espace disque, sauvegarde `backups/pre-migration-v<N>-<horodatage>.sqlite`. Chaque migration est transactionnelle : un échec annule tout et laisse la base inchangée (testé). Une migration déjà appliquée dont le fichier a été modifié est refusée (checksum).

Retour arrière manuel après une mise à jour : arrêter l'application, remplacer `qlab.sqlite` par la sauvegarde pré-migration correspondante, revenir à la version précédente du code.

Les mises à jour ne suppriment jamais campagnes, génomes, résultats ni datasets ; un composant produisant des résultats différents change de version, ce qui crée de nouvelles évaluations sans réécrire les anciennes.
