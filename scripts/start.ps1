# Démarre l'interface (qui lance le moteur local sur 127.0.0.1).
$root = Split-Path -Parent $PSScriptRoot
Push-Location "$root\app"
npx electron .
Pop-Location
