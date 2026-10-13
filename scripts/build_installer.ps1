# Construit l'installateur Windows autonome (NSIS) : Python 3.13 standalone + dépendances embarqués.
# La machine cible n'a besoin ni de uv ni de Python. Usage : powershell -ExecutionPolicy Bypass -File scripts\build_installer.ps1
#   -Version 0.2.0         fixe la version de l'application (app\package.json) avant le build
#   -Publish <dossier>     copie l'installateur puis latest.json (version, fichier, taille, SHA-512, notes)
#                          dans la source de mises à jour lue par l'application
#   -Notes "..."           notes de version affichées dans l'application
#   -NotesFile notes.txt   idem depuis un fichier UTF-8 (accents préservés, contrairement aux arguments de Windows PowerShell)
param([string]$Version = "", [string]$Publish = "", [string]$Notes = "", [string]$NotesFile = "")
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
if ($LASTEXITCODE -ne 0) { throw "electron-builder a échoué" }
Pop-Location
if ($NotesFile) { $Notes = [IO.File]::ReadAllText((Resolve-Path $NotesFile), [Text.Encoding]::UTF8).Trim() }
$ver = (Get-Content "$root\app\package.json" -Raw | ConvertFrom-Json).version
$exe = Get-Item "$root\app\release-installer\QLab Setup $ver.exe"
$manifest = [ordered]@{
    version = $ver; file = $exe.Name; size = $exe.Length
    sha512 = (Get-FileHash -Algorithm SHA512 $exe.FullName).Hash.ToLower()
    released_at = (Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ"); notes = $Notes
}
[IO.File]::WriteAllText("$root\app\release-installer\latest.json", ($manifest | ConvertTo-Json), (New-Object Text.UTF8Encoding $false))
Write-Host "Installateur : $($exe.FullName) ($([math]::Round($exe.Length / 1MB)) Mo)"
if ($Publish) {
    New-Item -ItemType Directory -Force $Publish | Out-Null
    Copy-Item $exe.FullName $Publish -Force
    # manifeste en dernier : une vérification pendant la copie ne voit jamais un manifeste sans son fichier
    Copy-Item "$root\app\release-installer\latest.json" $Publish -Force
    Write-Host "Publié dans $Publish (version $ver)"
}
