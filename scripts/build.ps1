param([string]$Python = "python", [string]$OutputDirectory = "dist")
$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent $PSScriptRoot)
& $Python -m venv .venv
if ($LASTEXITCODE -ne 0) { throw "Could not create the build environment." }
$BuildPython = Join-Path (Get-Location) ".venv\Scripts\python.exe"
$env:PYINSTALLER_CONFIG_DIR = Join-Path (Get-Location) "build\pyinstaller-cache"
& $BuildPython -m pip install --disable-pip-version-check --no-cache-dir "pyinstaller==6.22.3"
if ($LASTEXITCODE -ne 0) { throw "Could not install PyInstaller." }
& $BuildPython -m unittest discover -s tests -v
if ($LASTEXITCODE -ne 0) { throw "Tests failed; executable was not built." }
& $BuildPython -m PyInstaller --noconfirm --clean --onefile --windowed --name "Retro-Trans" --add-data 'retro_trans/resources;retro_trans/resources' --distpath $OutputDirectory launch.py
if ($LASTEXITCODE -ne 0) { throw "Packaging failed." }
$RuntimeHome = & $BuildPython -c "import sys; print(sys.base_prefix)"
$LicensesDirectory = Join-Path $OutputDirectory 'licenses'
New-Item -ItemType Directory -Force $LicensesDirectory | Out-Null
Copy-Item -LiteralPath (Join-Path $RuntimeHome 'LICENSE.txt') -Destination (Join-Path $LicensesDirectory 'Python-LICENSE.txt')
$TkLicense = Join-Path $RuntimeHome 'tcl\tk8.6\license.terms'
if (Test-Path -LiteralPath $TkLicense) {
    Copy-Item -LiteralPath $TkLicense -Destination (Join-Path $LicensesDirectory 'TclTk-LICENSE.txt')
}
Copy-Item -LiteralPath README.md,THIRD_PARTY_NOTICES.md -Destination $OutputDirectory
Copy-Item -LiteralPath 'retro_trans\resources\XDELTA-LICENSE.txt' -Destination $LicensesDirectory
& $BuildPython scripts\make_update_metadata.py $OutputDirectory
if ($LASTEXITCODE -ne 0) { throw "Could not generate update metadata." }
$PackageFiles = @('Retro-Trans.exe', 'README.md', 'THIRD_PARTY_NOTICES.md', 'licenses') | ForEach-Object { Join-Path $OutputDirectory $_ }
$PackagePath = Join-Path $OutputDirectory 'Retro-Trans-Windows.zip'
Compress-Archive -LiteralPath $PackageFiles -DestinationPath $PackagePath -Force
Write-Output "Ready: $(Join-Path $OutputDirectory 'Retro-Trans.exe')"
Write-Output "Shareable package: $PackagePath"
