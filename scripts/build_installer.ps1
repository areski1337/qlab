# Construit l'installateur Windows autonome (NSIS) : Python 3.13 standalone + dépendances embarqués.
# La machine cible n'a besoin ni de uv ni de Python. Usage : powershell -ExecutionPolicy Bypass -File scripts\build_installer.ps1
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$build = "$root\app\build"
$py = "$build\python"

if ($Version) {
    if ($Version -notmatch '^\d+\.\d+\.\d+$') { throw "version invalide : $Version (x.y.z attendu)" }
    Push-Location "$root\app"; npm version $Version --no-git-tag-version --allow-same-version | Out-Null; Pop-Location
}

Write-Host "1/4 Python standalone (python-build-standalone via uv)"
uv python install 3.13 | Out-Null
# Recherche hors du projet : dans engine\, uv renverrait le venv du projet (Scripts\) au lieu de l'installation autonome.
Push-Location $env:TEMP
$src = Split-Path -Parent (uv python find 3.13)
Pop-Location
$real = (Get-Item $src).Target
if ($real) { $src = $real }
if (-not (Test-Path "$src\Lib\os.py")) { throw "installation Python autonome introuvable : $src" }
if (Test-Path $build) { Remove-Item -Recurse -Force $build }
New-Item -ItemType Directory -Force $build | Out-Null
Copy-Item -Recurse $src $py

Write-Host "2/4 Dépendances du moteur dans le Python embarqué (copie locale, jamais l'installation partagée)"
Push-Location "$root\engine"
uv export --no-dev --no-hashes --no-emit-project --format requirements-txt -o "$build\requirements.txt" | Out-Null
Pop-Location
uv pip install --python "$py\python.exe" --break-system-packages -r "$build\requirements.txt"
if ($LASTEXITCODE -ne 0) { throw "installation des dépendances échouée" }
& "$py\python.exe" -c "import sys, numpy, pandas, pyarrow, fastapi, uvicorn, jsonschema, MetaTrader5; print('dépendances OK :', sys.prefix)"
if ($LASTEXITCODE -ne 0) { throw "dépendances absentes du Python embarqué" }

Write-Host "3/4 Build de l'interface"
Push-Location "$root\app"
npm run build

Write-Host "4/4 Installateur NSIS (sortie : app\release-installer)"
npx electron-builder --win nsis "-c.directories.output=release-installer"
Pop-Location
Get-ChildItem "$root\app\release-installer\*.exe" | ForEach-Object { Write-Host "Installateur : $($_.FullName) ($([math]::Round($_.Length / 1MB)) Mo)" }
