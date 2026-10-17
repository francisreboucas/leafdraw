#!/usr/bin/env bash
# Gera o LeafDraw para Linux ou macOS (PyInstaller), testa o executável e cria o pacote:
#   Linux: dist/LeafDraw-<versão>-linux-<arq>.tar.gz   macOS: dist/LeafDraw-<versão>-macos-<arq>.dmg
# Uso (na raiz do projeto):  bash packaging/build.sh
# O Python usado é o da .venv; outro pode ser indicado em PYTHON=/caminho/python.
set -euo pipefail
root="$(cd "$(dirname "$0")/.." && pwd)"
cd "$root"
py="${PYTHON:-$root/.venv/bin/python}"
os="$(uname -s)"
arch="$(uname -m)"
[ "$arch" = "aarch64" ] && arch=arm64
version="$("$py" -c "import leafdraw; print(leafdraw.__version__)")"
echo "LeafDraw $version ($os $arch)"

# conversor DWG (Rust): https://rustup.rs
cargo build --release --locked --manifest-path tools/dwgconv/Cargo.toml

QT_QPA_PLATFORM=offscreen "$py" packaging/make_icon.py
"$py" -m PyInstaller packaging/leafdraw.spec --noconfirm --distpath dist --workpath build

# autoteste do executável empacotado (catálogo, documento, 3D/OpenGL, folhas)
if [ "$os" = "Darwin" ]; then
    exe="dist/LeafDraw.app/Contents/MacOS/LeafDraw"
else
    exe="dist/LeafDraw/LeafDraw"
fi
out="$(mktemp -t leafdraw-smoke.XXXXXX)"
run=("$exe" --smoke-test "$out")
if [ "$os" = "Linux" ] && [ -z "${DISPLAY:-}${WAYLAND_DISPLAY:-}" ]; then
    run=(xvfb-run -a -s "-screen 0 1280x1024x24" "${run[@]}")  # sem tela: X virtual (apt install xvfb)
fi
"${run[@]}" &
pid=$!
for _ in $(seq 60); do
    kill -0 "$pid" 2>/dev/null || break
    sleep 1
done
if kill -0 "$pid" 2>/dev/null; then
    kill "$pid"
    echo "autoteste não terminou em 60 s" >&2
    exit 1
fi
code=0
wait "$pid" || code=$?
cat "$out"
rm -f "$out"
[ "$code" -eq 0 ] || { echo "autoteste falhou (código $code)" >&2; exit 1; }

if [ "$os" = "Darwin" ]; then
    # imagem de disco com o aplicativo e um atalho para Aplicativos (arrastar para instalar)
    pkg="dist/LeafDraw-$version-macos-$arch.dmg"
    stage="$(mktemp -d)"
    cp -R dist/LeafDraw.app "$stage/"
    ln -s /Applications "$stage/Aplicativos"
    rm -f "$pkg"
    hdiutil create -volname "LeafDraw $version" -srcfolder "$stage" -fs HFS+ -format UDZO -ov "$pkg"
    rm -rf "$stage"
else
    # pasta portátil + atalho do menu de aplicativos (instalar.sh)
    install -m 644 leafdraw/resources/icon.png dist/LeafDraw/leafdraw.png
    install -m 644 packaging/linux/leafdraw.desktop dist/LeafDraw/leafdraw.desktop
    install -m 755 packaging/linux/instalar.sh dist/LeafDraw/instalar.sh
    pkg="dist/LeafDraw-$version-linux-$arch.tar.gz"
    tar -czf "$pkg" -C dist LeafDraw
fi
ls -lh "$pkg"
