# LeafDraw

CAD para paisagismo em Python, com Qt for Python (PySide6, LGPLv3) e moderngl.

## Executar

```powershell
python -m venv .venv
.venv\Scripts\python -m pip install -e .[dev]
.venv\Scripts\python -m leafdraw            # ou: leafdraw projeto.leaf
.venv\Scripts\python -m pytest              # testes do núcleo
```

## Estrutura

```
leafdraw/
  core/            modelo, sem interface gráfica (testável com pytest)
    document.py    Document: entidades, camadas, undo stack, sinais
    entities.py    Line, Polyline, Circle, Arc, Text, Dimension, Hatch, Plant (imutáveis, metros, Y para cima)
    geom.py        transformações afins, interseções, perpendicular, tesselação
    editing.py     offset, explodir, contorno de hachura (Shapely)
    coords.py      interpretação da entrada digitada
    dxf_io.py      importação/exportação DXF e DWG (ezdxf)
    commands.py    AddEntities / RemoveEntities / ReplaceEntities (QUndoCommand)
    catalog.py     catálogo de espécies (resources/catalog.json)
    fileio.py      arquivo .leaf (zip com document.json)
  ui/
    main_window.py janela, menus, barras, docks, status
    viewport2d.py  planta (QGraphicsView): grade, zoom, pan, snap, arrastar e soltar
    items2d.py     itens gráficos, gizmo de mover, marcador de snap
    tools.py       ferramentas de desenho e de edição
    commandline.py linha de comando
    dxf_dialog.py  opções de importação
    viewport3d.py  vista 3D (moderngl): câmera orbital, plantas por instancing
    panels/        camadas, Gerenciador de Objetos (catálogo), propriedades
```

O `Document` é a fonte única da verdade. As vistas 2D e 3D apenas reagem aos
sinais dele, e toda edição de entidade passa por um comando desfazível.

## Linha de comando

Digite em qualquer lugar do viewport 2D: as teclas vão para a linha de comando.
Enter ou Espaço confirmam; Enter vazio termina a ferramenta ou repete o último comando.

| Comando | Aliases |
|---|---|
| Linha, Polilinha, Retângulo, Círculo, Arco | L, PL, REC, C, A |
| Texto, Cota, Hachura, Planta | T, COT, H, PLANTA |
| Mover, Copiar, Rotacionar, Escalar, Espelhar | M, CO, RO, SC, MI |
| Offset, Explodir, Apagar, Medir | O, X, E, DI |
| Zoom extensão, Desfazer, Importar/Exportar DXF, Ajuda | Z, U, IMPORTAR/EXPORTAR, ? |

Coordenadas: `10,5` (absoluta), `@3,4` (relativa), `@5<45` (polar), ou um número
solto para "distância na direção do cursor". Quando a ferramenta pede um número
(raio, ângulo, fator), `2,5` vale 2,5; para digitar um ponto com decimais use `;`
como separador: `2,5;3`.

Opções: polilinha `F` fecha; hachura `S D X L G P PE` escolhe o padrão e um número
define o módulo.

## Atalhos

| Tecla | Ação |
|---|---|
| Esc | Cancela a operação; um segundo Esc volta para Selecionar |
| Del | Exclui a seleção |
| Home | Zoom extensão (2D e 3D) |
| F3 / F9 / F8 | Snap em objetos, snap na grade, modo orto |
| F5 / F6 / F7 | Layout: só 2D, só 3D, 2D + 3D |
| Ctrl+I / Ctrl+Shift+E | Importar DXF/DWG, exportar DXF |
| Roda / botão do meio | Zoom e pan (2D) |
| 3D: arrastar com o botão esquerdo | Orbitar |
| 3D: botão do meio, direito ou Shift + arrastar | Pan |

Seleção por janela: arrastar da esquerda para a direita seleciona só o que
estiver inteiro dentro; da direita para a esquerda seleciona o que cruzar.
O botão OBJETO da barra de status tem um menu com os modos de snap
(extremidade, meio, centro, quadrante, interseção, perpendicular, próximo).

Para inserir plantas, arraste uma espécie do Gerenciador de Objetos para a
planta, ou dê duplo clique nela e clique no desenho.

## DXF e DWG

A importação lê LINE, (LW)POLYLINE, CIRCLE, ARC, ELLIPSE, SPLINE, TEXT, MTEXT,
HATCH, SOLID, cotas lineares e alinhadas, e blocos (INSERT, explodidos, com
atributos). As camadas vêm com cor, visibilidade e bloqueio. O diálogo deixa
escolher a unidade e trazer desenhos com coordenadas UTM para perto da origem.
A exportação grava em metros (R2018); plantas viram blocos `LD_<espécie>`,
que voltam a ser plantas ao reimportar.

DWG funciona se o [ODA File Converter](https://www.opendesign.com/guestfiles/oda_file_converter)
(gratuito) estiver instalado.

## Roteiro

1. **Base** (feito): janela, docks, camadas, undo/redo, arquivo `.leaf`, 2D, 3D básico, catálogo
2. **CAD 2D** (feito): arco, texto, cota, hachura, snaps, linha de comando, edição, DXF/DWG
3. Paisagismo: distribuição de plantas em área e em linha, quantitativos, edição do catálogo, aparar/estender, grips
4. Compositor de folhas: layouts A0 a A4, janelas de vista em escala, carimbo, legenda, PDF
5. 3D: picking, gizmos 3D, terreno, modelos melhores de plantas
