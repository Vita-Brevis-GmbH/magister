# Das Payload des Windows-Pakets bauen — der eine Schritt, der Windows braucht.
#
#     cd agent
#     .\packaging\windows\build-payload.ps1
#
# Ergebnis: `dist\magister-connector\` und daneben `magister-connector-payload.zip`.
# Das ZIP auf den Plattform-Server bringen (scp, Fileshare, USB) und dort:
#
#     ./scripts/agentenpakete.sh msi magister-connector-payload.zip
#
# Warum zweigeteilt: PyInstaller friert die Laufzeit ein, auf der es selbst
# läuft — ein Windows-Programm entsteht nur unter Windows. Das MSI drumherum
# baut Linux mit `wixl`, damit die WiX-Quelle auf jeder Maschine prüfbar
# bleibt (README.md in diesem Verzeichnis).
#
# Auf einem Domaincontroller hat dieses Skript nichts zu suchen: es lädt
# Abhängigkeiten aus dem Netz. Irgendein Windows mit Python genügt.

$ErrorActionPreference = "Stop"

$hier = Split-Path -Parent $MyInvocation.MyCommand.Path
$agent = Resolve-Path (Join-Path $hier "..\..")
Set-Location $agent

if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    Write-Error @"
uv fehlt. Einmalig installieren:

    winget install --id=astral-sh.uv -e
    #  oder:  powershell -c "irm https://astral.sh/uv/install.ps1 | iex"
"@
}

Write-Host "==> Abhängigkeiten" -ForegroundColor Cyan
uv python install 3.12
uv sync --extra packaging
if ($LASTEXITCODE -ne 0) { throw "uv sync ist gescheitert." }

Write-Host "==> PyInstaller" -ForegroundColor Cyan
uv run pyinstaller --clean --noconfirm packaging/windows/magister-connector.spec
if ($LASTEXITCODE -ne 0) { throw "PyInstaller ist gescheitert." }

$dist = Join-Path $agent "dist\magister-connector"
Copy-Item deploy\config.example.json $dist\ -Force
Copy-Item packaging\windows\INSTALL.txt $dist\ -Force

# Der Test, der zählt: nicht ob PyInstaller gelaufen ist, sondern ob das
# Ergebnis startet. Ein fehlender hiddenimport fällt genau hier auf — und
# sonst erst beim Kunden. Dieselben drei Aufrufe wie in agent-ci.yml.
Write-Host "==> Das eingefrorene Programm antwortet" -ForegroundColor Cyan
& "$dist\magister-connector.exe" --version
if ($LASTEXITCODE -ne 0) { throw "--version ist gescheitert." }
& "$dist\magister-connector.exe" --help | Out-Null
if ($LASTEXITCODE -ne 0) { throw "--help ist gescheitert." }
& "$dist\magister-connector.exe" --config nichts.json check | Out-Null
if ($LASTEXITCODE -ne 1) {
    throw "check ohne Konfiguration gab $LASTEXITCODE zurueck, erwartet 1."
}

$zip = Join-Path $agent "magister-connector-payload.zip"
if (Test-Path $zip) { Remove-Item $zip }
Compress-Archive -Path "$dist\*" -DestinationPath $zip
$groesse = "{0:N1} MiB" -f ((Get-Item $zip).Length / 1MB)

Write-Host ""
Write-Host "Payload: $dist" -ForegroundColor Green
Write-Host "Zum Mitnehmen: $zip ($groesse)" -ForegroundColor Green
Write-Host ""
Write-Host "Auf dem Plattform-Server weiter:"
Write-Host "    ./scripts/agentenpakete.sh msi magister-connector-payload.zip"
