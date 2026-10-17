# Gera dist\LeafDraw (PyInstaller), testa o executável, cria o instalador (Inno Setup) e um zip portátil.
# Uso (na raiz do projeto):  powershell -ExecutionPolicy Bypass -File packaging\build.ps1
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
$py = Join-Path $root ".venv\Scripts\python.exe"
$version = (& $py -c "import leafdraw; print(leafdraw.__version__)").Trim()
Write-Host "LeafDraw $version"

# conversor DWG (Rust): https://rustup.rs
cargo build --release --locked --manifest-path tools\dwgconv\Cargo.toml
if ($LASTEXITCODE -ne 0) { throw "compilação do dwgconv falhou" }

& $py packaging\make_icon.py
& $py -m PyInstaller packaging\leafdraw.spec --noconfirm --distpath dist --workpath build
if ($LASTEXITCODE -ne 0) { throw "PyInstaller falhou" }

# autoteste do executável empacotado (catálogo, documento, 3D/OpenGL, folhas)
$out = Join-Path $env:TEMP "leafdraw-smoke.txt"
Remove-Item $out -ErrorAction SilentlyContinue
$p = Start-Process -FilePath "dist\LeafDraw\LeafDraw.exe" -ArgumentList "--smoke-test", "`"$out`"" -PassThru
if (-not $p.WaitForExit(60000)) { $p.Kill(); throw "autoteste não terminou em 60 s" }
Get-Content $out
if ($p.ExitCode -ne 0) { throw "autoteste falhou (código $($p.ExitCode))" }

$iscc = @("$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe", "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe") |
    Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $iscc) { throw "Inno Setup 6 não encontrado (winget install JRSoftware.InnoSetup)" }
& $iscc /Q "/DAppVersion=$version" "/DDistDir=$root\dist\LeafDraw" packaging\installer.iss
if ($LASTEXITCODE -ne 0) { throw "Inno Setup falhou" }

$zip = "dist\LeafDraw-$version-portable-win64.zip"
Remove-Item $zip -ErrorAction SilentlyContinue
Compress-Archive -Path "dist\LeafDraw" -DestinationPath $zip
Get-ChildItem "dist\LeafDraw-$version-*" | Select-Object Name, @{n = "MB"; e = { [math]::Round($_.Length / 1MB, 1) } }
