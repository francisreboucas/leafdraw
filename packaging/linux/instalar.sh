#!/bin/sh
# Põe o LeafDraw no menu de aplicativos do usuário e associa os arquivos .leaf a ele.
# Rode de dentro da pasta extraída:  ./instalar.sh   (para desfazer: ./instalar.sh --remover)
set -e
dir="$(cd "$(dirname "$0")" && pwd)"
data="${XDG_DATA_HOME:-$HOME/.local/share}"
apps="$data/applications"
icons="$data/icons/hicolor/256x256/apps"
mime="$data/mime/packages"

if [ "${1:-}" = "--remover" ]; then
    rm -f "$apps/leafdraw.desktop" "$icons/leafdraw.png" "$mime/leafdraw.xml"
else
    mkdir -p "$apps" "$icons" "$mime"
    cp "$dir/leafdraw.png" "$icons/leafdraw.png"
    sed "s|^Exec=.*|Exec=\"$dir/LeafDraw\" %f|" "$dir/leafdraw.desktop" > "$apps/leafdraw.desktop"
    cat > "$mime/leafdraw.xml" <<XML
<?xml version="1.0" encoding="UTF-8"?>
<mime-info xmlns="http://www.freedesktop.org/standards/shared-mime-info">
  <mime-type type="application/x-leafdraw">
    <comment>Projeto LeafDraw</comment>
    <icon name="leafdraw"/>
    <glob pattern="*.leaf"/>
  </mime-type>
</mime-info>
XML
fi
update-mime-database "$data/mime" >/dev/null 2>&1 || true
update-desktop-database "$apps" >/dev/null 2>&1 || true
gtk-update-icon-cache -q "$data/icons/hicolor" >/dev/null 2>&1 || true
[ "${1:-}" = "--remover" ] && echo "LeafDraw removido do menu." || echo "LeafDraw adicionado ao menu de aplicativos."
