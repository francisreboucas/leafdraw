# LeafDraw

CAD para paisagismo em Python, com Qt for Python (PySide6, LGPLv3) e moderngl.

## Instalar (Windows)

Baixe o instalador `LeafDraw-<versão>-setup.exe` na página de
[releases](https://github.com/francisreboucas/leafdraw/releases) e execute. Não precisa de
administrador (instala para o seu usuário; o instalador oferece instalar para todos). Há também
uma versão portátil em `.zip`. Requer Windows 10/11 64 bits e placa de vídeo com OpenGL 3.3.

Como o instalador ainda não é assinado digitalmente, o Windows SmartScreen pode avisar
"o Windows protegeu o computador": clique em **Mais informações → Executar assim mesmo**.

## Executar a partir do código

```powershell
python -m venv .venv
.venv\Scripts\python -m pip install -e .[dev]
.venv\Scripts\python -m leafdraw            # ou: leafdraw projeto.leaf
.venv\Scripts\python -m pytest              # testes do núcleo
```

## Gerar o instalador

```powershell
.venv\Scripts\python -m pip install pyinstaller
winget install JRSoftware.InnoSetup          # uma vez
powershell -ExecutionPolicy Bypass -File packaging\build.ps1
```

O script gera `dist\LeafDraw\` (PyInstaller em modo pasta: as DLLs do Qt ficam separadas e
substituíveis, como pede a LGPL), roda `LeafDraw.exe --smoke-test` para validar o pacote
(catálogo, documento, 3D/OpenGL e folhas), cria o instalador com o Inno Setup e um zip portátil.
O ícone vem de `packaging/leaf.png` (`packaging/make_icon.py`).

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
    modify.py      aparar, estender, distribuir ao longo de caminhos
    schedule.py    quantitativos e CSV
    sheets.py      folhas, elementos (janela de vista, carimbo, quadro…) e layout padrão
    terrain.py     terreno: triangulação, cota em (x, y), linhas e polígonos assentados
    elevation.py   vistas (elevações): silhuetas de frente das espécies e montagem da vista
    symbol_blocks.py blocos DXF/DWG como desenho próprio (versão Planta ou Vista) de uma espécie
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
    catalog_dialog.py editor do catálogo de espécies
    composer.py    aba Folhas: edição das pranchas, PDF e impressão
    render.py      desenho das folhas (mesmo código para tela e PDF)
    project_dialog.py dados do projeto (carimbo)
    viewport3d.py  vista 3D (moderngl): câmera, seleção por clique, gizmo, envio à GPU
    scene3d.py     monta a cena 3D em arrays (sem OpenGL)
    plants3d.py    modelos procedurais de plantas e sombras
    gizmo3d.py     geometria e detecção do gizmo 3D
    panels/        camadas, Gerenciador de Objetos (catálogo), propriedades, quantitativos
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
| Aparar, Estender | TR, EST |
| Planta isolada, Maciço, Plantas em linha, Rótulo | PLANTA, MAC, LIN, ETQ |
| Quantitativos, Catálogo de espécies | QUANT, CATALOGO |
| Aba Folhas / Modelo, PDF das folhas, Dados do projeto | FOLHAS, MODELO, PDF, PROJETO |
| Curva de nível, Cota de nível | CN, NV |
| Vista (elevação) | VISTA, VI, ELEV |
| Zoom extensão, Desfazer, Importar/Exportar DXF, Ajuda | Z, U, IMPORTAR/EXPORTAR, ? |

Coordenadas: `10,5` (absoluta), `@3,4` (relativa), `@5<45` (polar), ou um número
solto para "distância na direção do cursor". Quando a ferramenta pede um número
(raio, ângulo, fator), `2,5` vale 2,5; para digitar um ponto com decimais use `;`
como separador: `2,5;3`.

Opções: polilinha `F` fecha; hachura `S D X L G P PE` escolhe o padrão e um número
define o módulo; maciço `T`/`Q` (malha triangular ou quadrada) e um número define o
espaçamento; plantas em linha `P` alterna entre "das pontas" e "centralizado".

## Paisagismo

- **Maciço** (MAC): clique dentro de uma área fechada; a espécie escolhida no
  Gerenciador de Objetos é plantada em malha triangular ou quadrada, recuada meio
  espaçamento das bordas. A quantidade de mudas é a contagem real da malha.
  Espaçamento, malha e ângulo podem ser editados depois em Propriedades.
  O maciço guarda o próprio contorno (não acompanha a polilinha usada para criá-lo).
- **Plantas em linha** (LIN): clique numa linha, polilinha, arco ou círculo, ajuste o
  espaçamento e confirme com Enter.
- **Rótulo** (ETQ): selecione plantas/maciços e clique onde vai o texto; cria o texto
  com a quantidade e linhas de chamada.
- **Quantitativos**: painel com isoladas, mudas em maciço, área de maciço e total por
  espécie, mais áreas de hachura por revestimento. Duplo clique seleciona a espécie no
  desenho. Exporta CSV (`;` e vírgula decimal, abre direto no Excel).
- **Catálogo**: crie, edite ou duplique espécies. Elas ficam no seu catálogo
  (`catalogo_usuario.json` na pasta de dados do aplicativo); o catálogo embutido não é
  alterado. O `.leaf` embute as espécies usadas, então o projeto abre igual em outra
  máquina.
- **Trocar espécie**: selecione plantas ou maciços e escolha outra espécie em Propriedades.
- **Grips**: com objetos selecionados, arraste os quadrados azuis para mover vértices,
  pontas, centros, raio ou a linha de cota.

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
| 3D: clique / Ctrl+clique | Seleciona / acrescenta à seleção (sincronizado com o 2D) |
| 3D: gizmo | Setas X/Y e quadrado XY movem; o anel gira em torno de Z (Shift: passos de 15°) |
| 3D: F | Enquadra a seleção |

Seleção por janela: arrastar da esquerda para a direita seleciona só o que
estiver inteiro dentro; da direita para a esquerda seleciona o que cruzar.
O botão OBJETO da barra de status tem um menu com os modos de snap
(extremidade, meio, centro, quadrante, interseção, perpendicular, próximo).

Para inserir plantas, arraste uma espécie do Gerenciador de Objetos para a
planta, ou dê duplo clique nela e clique no desenho.

## Terreno e 3D

- **Curva de nível** (CN): desenhe como uma polilinha; digite um número antes do 1º
  vértice para definir a cota. A cada curva concluída a cota sobe 1 m.
  **Cota de nível** (NV): pontos cotados.
- O terreno 3D é uma triangulação (TIN) de todas as curvas e cotas visíveis. Plantas,
  linhas, hachuras e maciços se assentam sobre ele; fora da área levantada o chão é plano
  na cota mais baixa. O Z do terreno sob o cursor aparece na barra de status.
- Vistas → "3D: Exagero vertical do terreno" (1×, 2×, 5×, 10×).
- Na importação DXF, LWPOLYLINE com elevação, POLYLINE 3D de cota constante e LINE com Z
  viram curvas de nível; POINT com Z vira cota de nível.
- Plantas 3D procedurais: copas irregulares, palmeiras com folhas, arbustos orgânicos,
  variação natural de tamanho/cor/rotação e sombras difusas no chão.

## Vistas (elevações)

Cada espécie do Gerenciador de Objetos tem duas versões, mostradas lado a lado abaixo da
lista: **Planta** (o símbolo visto de cima) e **Vista** (a silhueta de frente).

- Sem bloco próprio, as duas versões são geradas pelo tipo de símbolo (árvore, palmeira,
  arbusto, forração), pela altura e pela copa.
- No **Catálogo de espécies**, "Importar bloco…" troca a Planta ou a Vista por um bloco de um
  DXF/DWG seu (ou pelo desenho inteiro do arquivo). A Planta é ajustada ao diâmetro da copa;
  a Vista, à copa (largura) e à altura, com a base do bloco no chão. "Automático" volta ao
  desenho gerado. Os blocos vão junto com a espécie no `.leaf`.
- **Vista** (VISTA): clique os dois pontos da linha de corte, depois o lado para onde a vista
  olha (digite um número para mudar a profundidade; 0 = sem limite) e, por fim, onde fica o
  desenho. Entram as plantas isoladas e as mudas de maciço à frente da linha, dentro da
  profundidade, cada uma apoiada no terreno; as mais distantes saem mais claras.
- A vista é **associativa**: mover, trocar ou apagar plantas e mudar o terreno refaz o desenho.
  Em Propriedades: nome, lado ("Olhar para o outro lado"), profundidade, cota da base e altura
  do texto. Mover/copiar a vista desloca só o desenho; a linha de corte se ajusta pelos grips
  (pontas e meio). Para levá-la a uma prancha, enquadre o desenho numa janela de vista 2D.
- Na exportação DXF/DWG a vista sai como linhas, polilinhas e textos comuns.

## Folhas de impressão

Aba **Folhas** (Ctrl+2):

- **Nova…** cria uma prancha A0–A4 (paisagem ou retrato) com margens ABNT (25 mm à
  esquerda), carimbo, norte, escala gráfica, quadro de vegetação (A0–A2 paisagem) e uma
  janela de vista já enquadrando o desenho numa escala padrão.
- Elementos: **janela de vista 2D** (escala 1:n, centro, camadas visíveis por janela),
  **janela de vista 3D** (usa a câmera atual do 3D), **carimbo**, **quadro de vegetação**
  (símbolo, nome popular, científico, altura, copa, quantidade, total e áreas de
  revestimento), **texto**, **norte** e **escala gráfica**.
- Arraste para mover, alça azul para redimensionar; numa janela de vista, Ctrl+arrastar
  faz pan e Ctrl+roda troca a escala; duplo clique abre a região no Modelo.
- **Dados do projeto** (Arquivo → Dados do projeto) preenchem o carimbo de todas as folhas;
  o conteúdo é o título da folha e a escala vem da 1ª janela de vista.
- **PDF** vetorial no tamanho real do papel (uma folha ou todas, Ctrl+Shift+P) e
  **Imprimir** (Ctrl+P), que ajusta a folha ao papel da impressora.
- Espessura de linha por camada (coluna "Esp." no painel Camadas). Cores muito claras,
  feitas para o fundo escuro da tela, saem pretas no papel.

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
3. **Paisagismo** (feito): maciços, plantas em linha, rótulos, quantitativos, catálogo editável, aparar/estender, grips
4. **Folhas** (feito): pranchas A0–A4, janelas de vista 2D/3D em escala, carimbo, quadro de vegetação, norte, escala gráfica, PDF e impressão
5. **3D avançado** (feito): seleção por clique, gizmo 3D, terreno por curvas/cotas de nível, plantas procedurais e sombras
