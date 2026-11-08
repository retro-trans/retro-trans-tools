param([string]$Python = "python", [string]$OutputDirectory = "dist")
$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent $PSScriptRoot)
$BuildPython = Join-Path (Get-Location) ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $BuildPython)) {
    & $Python -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw "Could not create the build environment." }
}
$env:PYINSTALLER_CONFIG_DIR = Join-Path (Get-Location) "build\pyinstaller-cache"
& $BuildPython -m pip install --disable-pip-version-check --no-cache-dir "pyinstaller==6.22.3"
if ($LASTEXITCODE -ne 0) { throw "Could not install PyInstaller." }
& $BuildPython -m pip install --disable-pip-version-check --no-cache-dir -e .
if ($LASTEXITCODE -ne 0) { throw "Could not install application dependencies." }
if (-not (Test-Path -LiteralPath 'retro_trans/resources/native/dcp/win-x64/engine.json')) {
    & $BuildPython scripts/bundle_dcp.py --write
    if ($LASTEXITCODE -ne 0) { throw "Could not bundle the pinned DCP engine." }
}
if (-not (Test-Path -LiteralPath 'retro_trans/resources/dolphin-tool-windows.zip')) {
    & $BuildPython scripts/bundle_rvz.py --write
    if ($LASTEXITCODE -ne 0) { throw "Could not bundle the pinned RVZ converter." }
}
& $BuildPython -m unittest discover -s tests -v
if ($LASTEXITCODE -ne 0) { throw "Tests failed; executable was not built." }
$TlsRuntimeData = & $BuildPython -c "from pathlib import Path; import ssl; p=Path(ssl.__file__).with_name('codex-rejected-cas.pem'); print(p if p.is_file() else '')"
$TlsRuntimeArguments = @()
if ($TlsRuntimeData) {
    # Some build runtimes load an adjacent CA-policy file from ssl.py. Preserve
    # that runtime's policy; never disable TLS verification to make it work.
    $TlsRuntimeArguments = @('--add-data', "$TlsRuntimeData;.")
}
& $BuildPython -m PyInstaller --noconfirm --clean --onefile --windowed --name "Retro-Trans" --add-data 'retro_trans/resources;retro_trans/resources' @TlsRuntimeArguments --distpath $OutputDirectory launch.py
if ($LASTEXITCODE -ne 0) { throw "Packaging failed." }
$RuntimeHome = & $BuildPython -c "import sys; print(sys.base_prefix)"
$LicensesDirectory = Join-Path $OutputDirectory 'licenses'
New-Item -ItemType Directory -Force $LicensesDirectory | Out-Null
$DcpNotices = Join-Path $LicensesDirectory 'dcp'
New-Item -ItemType Directory -Force $DcpNotices | Out-Null
Copy-Item -LiteralPath 'retro_trans/resources/native/dcp/win-x64/UDP-GPL-3.0.txt','retro_trans/resources/native/dcp/win-x64/CORRESPONDING-SOURCE.zip' -Destination $DcpNotices
foreach ($Notice in @('DOTNET-LICENSE.txt','DOTNET-THIRD-PARTY-NOTICES.txt','System.IO.Hashing-LICENSE.txt','System.IO.Hashing-THIRD-PARTY-NOTICES.txt')) {
    $NoticePath = Join-Path 'retro_trans/resources/native/dcp/win-x64' $Notice
    if (-not (Test-Path -LiteralPath $NoticePath)) { throw 'Rebuild the pinned DCP engine in a clean resource folder to include its dependency notices.' }
    Copy-Item -LiteralPath $NoticePath -Destination $DcpNotices
}
Copy-Item -LiteralPath (Join-Path $RuntimeHome 'LICENSE.txt') -Destination (Join-Path $LicensesDirectory 'Python-LICENSE.txt')
$TkLicense = Join-Path $RuntimeHome 'tcl\tk8.6\license.terms'
if (Test-Path -LiteralPath $TkLicense) {
    Copy-Item -LiteralPath $TkLicense -Destination (Join-Path $LicensesDirectory 'TclTk-LICENSE.txt')
}
Copy-Item -LiteralPath README.md,THIRD_PARTY_NOTICES.md -Destination $OutputDirectory
New-Item -ItemType Directory -Force (Join-Path $OutputDirectory 'docs') | Out-Null
Copy-Item -LiteralPath 'docs/RVZ.md' -Destination (Join-Path $OutputDirectory 'docs/RVZ.md')
Copy-Item -LiteralPath 'docs/PS3_DLC.md' -Destination (Join-Path $OutputDirectory 'docs/PS3_DLC.md')
Copy-Item -LiteralPath 'retro_trans\resources\XDELTA-LICENSE.txt' -Destination $LicensesDirectory
& $BuildPython -m retro_trans.dependency_notices $LicensesDirectory
if ($LASTEXITCODE -ne 0) { throw "Could not package cryptography dependency notices." }
& $BuildPython -c "from retro_trans.chd import copy_notices; import sys; copy_notices(sys.argv[1])" (Join-Path $LicensesDirectory 'chdman')
if ($LASTEXITCODE -ne 0) { throw "Could not package CHD engine notices." }
& $BuildPython -c "from retro_trans.rvz import copy_notices; import sys; copy_notices(sys.argv[1])" (Join-Path $LicensesDirectory 'dolphin-tool')
if ($LASTEXITCODE -ne 0) { throw "Could not package RVZ converter notices." }
& $BuildPython scripts\make_update_metadata.py $OutputDirectory
if ($LASTEXITCODE -ne 0) { throw "Could not generate update metadata." }
$PackageFiles = @('Retro-Trans.exe', 'README.md', 'THIRD_PARTY_NOTICES.md', 'licenses', 'docs') | ForEach-Object { Join-Path $OutputDirectory $_ }
$PackagePath = Join-Path $OutputDirectory 'Retro-Trans-Windows.zip'
Compress-Archive -LiteralPath $PackageFiles -DestinationPath $PackagePath -Force
Write-Output "Ready: $(Join-Path $OutputDirectory 'Retro-Trans.exe')"
Write-Output "Shareable package: $PackagePath"
