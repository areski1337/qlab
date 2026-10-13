# Installation QLab (Windows). Idempotent. Aucune donnée utilisateur n'est supprimée.
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
function Need($cmd, $hint) { if (-not (Get-Command $cmd -ErrorAction SilentlyContinue)) { throw "$cmd introuvable : $hint" } }
Need uv "installer uv : https://docs.astral.sh/uv/"
Need node "installer Node.js 24 LTS"
Need npm "installé avec Node.js"
$free = (Get-PSDrive ($root.Substring(0,1))).Free / 1GB
if ($free -lt 3) { throw "espace disque insuffisant : $([math]::Round($free,1)) Go libres (3 Go requis)" }
Write-Host "1/4 Environnement Python (uv, Python 3.13)"
Push-Location "$root\engine"; uv sync; Pop-Location
Write-Host "2/4 Dépendances de l'interface"
Push-Location "$root\app"; npm ci; node node_modules/electron/install.js
Write-Host "3/4 Build de l'interface"
npm run build; Pop-Location
Write-Host "4/4 Tests rapides du moteur"
Push-Location "$root\engine"; uv run pytest -q; Pop-Location
$mt5 = "C:\Program Files\MetaTrader 5\terminal64.exe"
if (Test-Path $mt5) { Write-Host "MetaTrader 5 détecté : $mt5" } else { Write-Warning "MetaTrader 5 non détecté : import MT5, compilation et parité seront bloqués (recherche sur données existantes possible)" }
Write-Host "Installation terminée. Démarrer : scripts\start.ps1"
